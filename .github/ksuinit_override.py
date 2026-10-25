#!/usr/bin/env python3
"""ksuinit 补丁：从 metadata 分区加载 /ksu/kernelsu.ko（.ko 热更新）。

ksuinit 早于 ueventd，/dev/block/by-name/* 不存在；
本机 sysfs 也没有 PARTNAME，因此按「小分区 + ext4 + 标记文件」扫描。
"""
import sys

HELPER = r'''

// ==== ColorArchive: .ko 热更新 ====
// 扫描所有 4MB~96MB 的分区，只读挂载 ext4，寻找 /ksu/kernelsu.ko
fn try_load_from_partitions() -> Option<()> {
    let rd = match std::fs::read_dir("/sys/class/block") {
        Ok(r) => r,
        Err(e) => {
            log::error!("scan: read_dir failed: {:?}", e);
            return None;
        }
    };
    let mut tried = 0;
    for e in rd.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        let base = format!("/sys/class/block/{}", name);
        let uev = match std::fs::read_to_string(format!("{}/uevent", base)) {
            Ok(s) => s,
            Err(_) => continue,
        };
        if !uev.lines().any(|l| l == "DEVTYPE=partition") {
            continue;
        }
        let sectors: u64 = std::fs::read_to_string(format!("{}/size", base))
            .ok()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);
        let mb = sectors / 2048;
        if mb < 4 || mb > 96 {
            continue;
        }
        let devname = uev
            .lines()
            .find_map(|l| l.strip_prefix("DEVNAME="))
            .map(|s| s.to_string())
            .unwrap_or_else(|| name.clone());
        let dev = format!("/dev/block/{}", devname);
        if !std::path::Path::new(&dev).exists() {
            continue;
        }
        let _ = std::fs::create_dir_all("/mnt/kmeta");
        let c_dev = match CString::new(dev.clone()) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let c_dir = CString::new("/mnt/kmeta").unwrap();
        let c_fs = CString::new("ext4").unwrap();
        let rc = unsafe {
            mount(
                c_dev.as_ptr(),
                c_dir.as_ptr(),
                c_fs.as_ptr(),
                1, // MS_RDONLY
                std::ptr::null(),
            )
        };
        if rc != 0 {
            continue;
        }
        tried += 1;
        let path = "/mnt/kmeta/ksu/kernelsu.ko";
        let sz = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
        if sz > 0 {
            log::info!("override: {} on {} ({} bytes)", path, dev, sz);
            match load_module_from_path(path) {
                Ok(()) => {
                    log::info!("override: loaded OK");
                    let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
                    return Some(());
                }
                Err(err) => log::error!("override: load failed {:?}", err),
            }
        }
        let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
    }
    log::info!("override: scanned ext4 partitions: {} mounted", tried);
    None
}

fn load_module_preferred() -> Result<()> {
    for p in [
        "/dev/block/by-name/metadata",
        "/dev/block/bootdevice/by-name/metadata",
    ] {
        if !std::path::Path::new(p).exists() {
            continue;
        }
        let _ = std::fs::create_dir_all("/mnt/kmeta");
        let c_dev = CString::new(p)?;
        let c_dir = CString::new("/mnt/kmeta")?;
        let c_fs = CString::new("ext4")?;
        let rc = unsafe { mount(c_dev.as_ptr(), c_dir.as_ptr(), c_fs.as_ptr(), 1, std::ptr::null()) };
        if rc == 0 {
            let path = "/mnt/kmeta/ksu/kernelsu.ko";
            if std::path::Path::new(path).exists() {
                log::info!("override: by-name {} -> {}", p, path);
                if load_module_from_path(path).is_ok() {
                    let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
                    return Ok(());
                }
            }
            let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
        }
    }
    if try_load_from_partitions().is_some() {
        return Ok(());
    }
    log::info!("fallback to ramdisk /kernelsu.ko");
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