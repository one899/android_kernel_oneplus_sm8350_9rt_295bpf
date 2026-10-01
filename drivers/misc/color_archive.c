// SPDX-License-Identifier: GPL-2.0-only
/*
 * color_archive.c - read the ColorArchive partition early in boot.
 *
 * The partition holds an f2fs image.  It is read before init runs, so the
 * usual /dev/block/by-name/ColorArchive symlink (created by init/ueventd)
 * is not available yet.  Instead this driver walks the GPT on the target
 * LUN itself and locates the partition by its GPT label.
 *
 * The GPT entry index maps 1:1 onto the partition number assigned by
 * block/partitions/efi.c (state->parts[i + 1]), so the block device is
 * /dev/<disk><index + 1>.
 */

#define pr_fmt(fmt) "color_archive: " fmt

#include <linux/blkdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/fs_context.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/mount.h>
#include <linux/namei.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/types.h>
#include <linux/vmalloc.h>

#define CA_COMPATIBLE		"oplus,color-archive"
#define CA_DISK_DEFAULT		"sda"
#define CA_PART_DEFAULT		"ColorArchive"
#define CA_FILE_DEFAULT		"/archive.bin"
#define CA_MAX_DATA		(16u * 1024u * 1024u)

#define CA_SECTOR_SIZE		512u
#define CA_BLOCK_SIZE		4096u
#define CA_GPT_ENTRIES_MAX	128u
#define CA_GPT_NAME_LEN		72u

struct ca_gpt_header {
	u8	signature[8];
	u32	revision;
	u32	header_size;
	u32	header_crc32;
	u32	reserved;
	u64	current_lba;
	u64	backup_lba;
	u64	first_usable_lba;
	u64	last_usable_lba;
	u8	disk_guid[16];
	u64	partition_entry_lba;
	u32	num_partition_entries;
	u32	sizeof_partition_entry;
	u32	partition_entry_array_crc32;
} __packed;

struct ca_gpt_entry {
	u8	type_guid[16];
	u8	unique_guid[16];
	u64	first_lba;
	u64	last_lba;
	u64	attributes;
	u8	name[CA_GPT_NAME_LEN];
} __packed;

static char *ca_disk_name;
static char *ca_part_name;
static char *ca_file_name;

static void *ca_data;
static size_t ca_data_len;

/*
 * Read exactly @len bytes at @pos from an already opened file.  Unlike
 * kernel_read() this loops until everything arrives, so a short read from
 * the block device cannot silently truncate the image.
 */
static int ca_read_exact(struct file *file, void *buf, size_t len, loff_t pos)
{
	size_t done = 0;

	while (done < len) {
		ssize_t ret = kernel_read(file, (char *)buf + done,
					  len - done, &pos);

		if (ret < 0)
			return ret;
		if (ret == 0)
			return -EIO;
		done += ret;
	}

	return 0;
}

/*
 * Compare a UTF-16LE GPT name field against an ASCII label.  GPT names are
 * not guaranteed to be NUL terminated inside the 72 byte field.
 */
static bool ca_gpt_name_match(const u8 *raw, const char *label)
{
	size_t i;

	for (i = 0; i < CA_GPT_NAME_LEN / 2 && label[i]; i++) {
		u16 c = raw[i * 2] | (raw[i * 2 + 1] << 8);

		if (c != (u16)(unsigned char)label[i])
			return false;
	}

	/* the label must be fully consumed and terminated in the field */
	if (label[i])
		return false;
	if (i >= CA_GPT_NAME_LEN / 2)
		return true;

	return (raw[i * 2] == 0 && raw[i * 2 + 1] == 0);
}

/*
 * Walk the GPT of @disk and return the partno of the entry labelled
 * @label, or a negative errno.  partno is 1 based and matches the number
 * the kernel assigns to the partition block device.
 */
static int ca_gpt_lookup_partno(const char *disk, const char *label)
{
	struct ca_gpt_header hdr;
	struct ca_gpt_entry *entries;
	struct file *file;
	char disk_path[64];
	size_t entry_bytes;
	loff_t pos;
	u32 i;
	int ret = -ENOENT;

	snprintf(disk_path, sizeof(disk_path), "/dev/%s", disk);

	file = filp_open(disk_path, O_RDONLY | O_LARGEFILE, 0);
	if (IS_ERR(file)) {
		pr_err("cannot open %s (%ld)\n", disk_path, PTR_ERR(file));
		return PTR_ERR(file);
	}

	/* LBA 1 holds the primary GPT header */
	pos = CA_BLOCK_SIZE;
	ret = ca_read_exact(file, &hdr, sizeof(hdr), pos);
	if (ret)
		goto out;

	if (memcmp(hdr.signature, "EFI PART", 8) != 0) {
		pr_err("%s: bad GPT signature\n", disk_path);
		ret = -EINVAL;
		goto out;
	}

	if (hdr.sizeof_partition_entry != sizeof(struct ca_gpt_entry)) {
		pr_err("%s: unexpected GPT entry size %u\n",
		       disk_path, hdr.sizeof_partition_entry);
		ret = -EINVAL;
		goto out;
	}

	if (hdr.num_partition_entries == 0 ||
	    hdr.num_partition_entries > CA_GPT_ENTRIES_MAX) {
		pr_err("%s: unexpected GPT entry count %u\n",
		       disk_path, hdr.num_partition_entries);
		ret = -EINVAL;
		goto out;
	}

	entry_bytes = (size_t)hdr.num_partition_entries *
		      sizeof(struct ca_gpt_entry);

	entries = vmalloc(entry_bytes);
	if (!entries) {
		ret = -ENOMEM;
		goto out;
	}

	pos = (loff_t)hdr.partition_entry_lba * CA_BLOCK_SIZE;
	ret = ca_read_exact(file, entries, entry_bytes, pos);
	if (ret) {
		vfree(entries);
		goto out;
	}

	ret = -ENOENT;
	for (i = 0; i < hdr.num_partition_entries; i++) {
		const struct ca_gpt_entry *e = &entries[i];
		bool empty = true;
		int j;

		for (j = 0; j < 16; j++) {
			if (e->type_guid[j]) {
				empty = false;
				break;
			}
		}
		if (empty)
			continue;

		if (ca_gpt_name_match(e->name, label)) {
			/* efi_partition() stores entry i at parts[i + 1] */
			ret = (int)i + 1;
			break;
		}
	}

	vfree(entries);

out:
	filp_close(file, NULL);
	return ret;
}

/*
 * Mount the f2fs image on @dev_path and read @file_name into a freshly
 * allocated buffer.  Returns 0 on success.
 */
static int ca_read_file(const char *dev_path, const char *file_name,
			void **out, size_t *out_len)
{
	struct fs_context *fc;
	struct vfsmount *mnt;
	struct file *file;
	void *buf = NULL;
	loff_t size;
	loff_t pos = 0;
	size_t len;
	int ret;

	fc = fsopen("f2fs", 0);
	if (IS_ERR(fc)) {
		pr_err("fsopen(f2fs) failed (%ld)\n", PTR_ERR(fc));
		return PTR_ERR(fc);
	}

	ret = vfs_parse_fs_string(fc, "source", dev_path, strlen(dev_path));
	if (ret)
		goto out_fc;

	mnt = fc_mount(fc);
	if (IS_ERR(mnt)) {
		ret = PTR_ERR(mnt);
		pr_err("mount f2fs on %s failed (%d)\n", dev_path, ret);
		goto out_fc;
	}

	file = file_open_root(mnt->mnt_root, mnt, file_name, O_RDONLY, 0);
	if (IS_ERR(file)) {
		ret = PTR_ERR(file);
		pr_warn("cannot open %s on %s (%d)\n",
			file_name, dev_path, ret);
		goto out_mnt;
	}

	size = i_size_read(file_inode(file));
	if (size <= 0) {
		pr_warn("%s is empty\n", file_name);
		ret = -ENODATA;
		goto out_file;
	}
	if (size > CA_MAX_DATA) {
		pr_warn("%s is too large (%lld)\n", file_name, size);
		ret = -EFBIG;
		goto out_file;
	}

	len = (size_t)size;
	buf = vzalloc(len);
	if (!buf) {
		ret = -ENOMEM;
		goto out_file;
	}

	ret = ca_read_exact(file, buf, len, pos);
	if (ret)
		goto out_file;

	*out = buf;
	*out_len = len;
	buf = NULL;

out_file:
	if (buf)
		vfree(buf);
	filp_close(file, NULL);
out_mnt:
	kern_unmount(mnt);
out_fc:
	put_fs_context(fc);
	return ret;
}

static int __init color_archive_init(void)
{
	struct device_node *np;
	const char *disk = CA_DISK_DEFAULT;
	const char *part = CA_PART_DEFAULT;
	const char *file = CA_FILE_DEFAULT;
	char dev_path[80];
	int partno;
	int ret;

	np = of_find_compatible_node(NULL, NULL, CA_COMPATIBLE);
	if (!np)
		return 0;

	if (!of_device_is_available(np)) {
		of_node_put(np);
		return 0;
	}

	of_property_read_string(np, "oplus,disk-name", &disk);
	of_property_read_string(np, "oplus,partition-name", &part);
	of_property_read_string(np, "oplus,file-name", &file);
	of_node_put(np);

	ca_disk_name = kstrdup(disk, GFP_KERNEL);
	ca_part_name = kstrdup(part, GFP_KERNEL);
	ca_file_name = kstrdup(file, GFP_KERNEL);

	/*
	 * Block devices probe asynchronously; make sure the UFS LUNs and
	 * their partitions exist before we try to open them.
	 */
	wait_for_device_probe();

	partno = ca_gpt_lookup_partno(disk, part);
	if (partno < 0) {
		pr_err("partition '%s' not found on %s (%d)\n",
		       part, disk, partno);
		return 0;
	}

	snprintf(dev_path, sizeof(dev_path), "/dev/%s%d", disk, partno);

	pr_info("found '%s' at %s\n", part, dev_path);

	ret = ca_read_file(dev_path, file, &ca_data, &ca_data_len);
	if (ret) {
		pr_err("read %s from %s failed (%d)\n", file, dev_path, ret);
		return 0;
	}

	pr_info("loaded %zu bytes from %s%s\n", ca_data_len, dev_path, file);
	return 0;
}

static void __exit color_archive_exit(void)
{
	vfree(ca_data);
	ca_data = NULL;
	ca_data_len = 0;
}

late_initcall_sync(color_archive_init);
module_exit(color_archive_exit);

MODULE_AUTHOR("OnePlus 9RT kernel");
MODULE_DESCRIPTION("Early reader for the ColorArchive partition");
MODULE_LICENSE("GPL v2");
