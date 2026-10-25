#!/usr/bin/env python3
"""ksuinit 补丁：从 metadata 分区加载 /ksu/kernelsu.ko（.ko 热更新）。

关键：ksuinit 早于 init，/dev 未挂载、/dev/block/* 不存在，
因此自行 mknod 创建块设备节点后再挂载。全程清理挂载。
"""
import sys

HELPER = r'''

// ==== ColorArchive: .ko 热更新 ====
fn umount_quiet(p: &str) {
    let _ = unmount(p, UnmountFlags::DETACH);
}

fn mknod_blk(path: &str, major: u32, minor: u32) -> i32 {
    let _ = std::fs::remove_file(path);
    let c = match CString::new(path) {
        Ok(c) => c,
        Err(_) => return -1,
    };
    // Linux new_encode_dev: (major << 8) | (minor & 0xff) | ((minor & ~0xff) << 12)
    let dev: u64 = ((major as u64) << 8)
        | ((minor as u64) & 0xff)
        | (((minor as u64) & !0xffu64) << 12);
    let mode: u32 = 0o060000 | 0o600; // S_IFBLK | 0600
    unsafe { mknod(c.as_ptr(), mode, dev) }
}

fn mount_ro(src: &str, tgt: &str, fstype: &str) -> i32 {
    let _ = std::fs::create_dir_all(tgt);
    let c_src = match CString::new(src) { Ok(c) => c, Err(_) => return -1 };
    let c_tgt = match CString::new(tgt) { Ok(c) => c, Err(_) => return -1 };
    let c_fs = match CString::new(fstype) { Ok(c) => c, Err(_) => return -1 };
    unsafe { mount(c_src.as_ptr(), c_tgt.as_ptr(), c_fs.as_ptr(), 1, std::ptr::null()) }
}

struct Cand {
    name: String,
    mb: u64,
    major: u32,
    minor: u32,
}

fn scan_candidates() -> Vec<Cand> {
    let mut out = Vec::new();
    let rd = match std::fs::read_dir("/mnt/ksys/class/block") {
        Ok(r) => r,
        Err(e) => {
            log::error!("override: read_dir failed {:?}", e);
            return out;
        }
    };
    for e in rd.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        // 分区名以数字结尾（sda10 / mmcblk0p5），排除整盘与 ram*
        if !name.chars().last().map(|c| c.is_ascii_digit()).unwrap_or(false) {
            continue;
        }
        if name.starts_with("ram") || name.starts_with("loop") {
            continue;
        }
        let base = format!("/mnt/ksys/class/block/{}", name);
        let sectors: u64 = std::fs::read_to_string(format!("{}/size", base))
            .ok()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);
        let mb = sectors / 2048;
        if mb < 4 || mb > 96 {
            continue;
        }
        let devs = std::fs::read_to_string(format!("{}/dev", base)).unwrap_or_default();
        let mut it = devs.trim().split(':');
        let major: u32 = it.next().and_then(|s| s.parse().ok()).unwrap_or(0);
        let minor: u32 = it.next().and_then(|s| s.parse().ok()).unwrap_or(0);
        if major == 0 {
            continue;
        }
        log::info!("override: cand {} {}MB {}:{}", name, mb, major, minor);
        out.push(Cand { name, mb, major, minor });
    }
    out
}

fn try_load_from_partitions() -> bool {
    let cands = scan_candidates();
    log::info!("override: {} candidates usable", cands.len());
    for c in cands {
        let node = "/ksu_blk";
        let rc = mknod_blk(node, c.major, c.minor);
        if rc != 0 {
            log::error!("override: mknod {} {}:{} rc={}", c.name, c.major, c.minor, rc);
            continue;
        }
        let mrc = mount_ro(node, "/mnt/kmeta", "ext4");
        if mrc != 0 {
            let _ = std::fs::remove_file(node);
            continue;
        }
        let path = "/mnt/kmeta/ksu/kernelsu.ko";
        let sz = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
        if sz > 0 {
            log::info!("override: FOUND {} on {} ({} bytes)", path, c.name, sz);
            if load_module_from_path(path).is_ok() {
                log::info!("override: loaded OK");
                umount_quiet("/mnt/kmeta");
                let _ = std::fs::remove_file(node);
                return true;
            }
            log::error!("override: load failed on {}", c.name);
        }
        umount_quiet("/mnt/kmeta");
        let _ = std::fs::remove_file(node);
    }
    false
}

fn load_module_preferred() -> Result<()> {
    let rc = mount_ro("sysfs", "/mnt/ksys", "sysfs");
    log::info!("override: sysfs mount rc={}", rc);
    let mut done = false;
    if rc == 0 || std::path::Path::new("/mnt/ksys/class/block").exists() {
        done = try_load_from_partitions();
    }
    umount_quiet("/mnt/ksys");
    if done {
        return Ok(());
    }
    log::info!("override: fallback to ramdisk");
    load_module_from_path("/kernelsu.ko")
}

unsafe extern "C" {
    fn mount(
        src: *const std::os::raw::c_char,
        tgt: *const std::os::raw::c_char,
        fstype: *const std::os::raw::c_char,
        flags: std::os::raw::c_ulong,
        data: *const std::os::raw::c_void,
    ) -> std::os::raw::c_int;
    fn mknod(
        path: *const std::os::raw::c_char,
        mode: u32,
        dev: u64,
    ) -> std::os::raw::c_int;
}
'''

def main(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    if "load_module_preferred" in src:
        print("already patched, skip")
        return 0
    old = '    if let Err(e) = load_module_from_path("/kernelsu.ko") {'
    new = '    if let Err(e) = load_module_preferred() {'
    if old not in src:
        print("!! anchor not found")
        return 1
    src = src.replace(old, new, 1) + HELPER
    open(path, "w", encoding="utf-8").write(src)
    print("patched:", path)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "userspace/ksuinit/src/init.rs"))