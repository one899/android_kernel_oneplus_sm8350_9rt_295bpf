#!/usr/bin/env python3
"""给 ksuinit 打补丁：优先从 /metadata/ksu/kernelsu.ko 加载（.ko 热更新）。"""
import sys

HELPER = r'''

// ==== ColorArchive: .ko 热更新 ====
// ksuinit 运行在 ueventd 之前，/dev/block/by-name/* 还不存在，
// 需要从 /sys/class/block/*/uevent 里按 PARTNAME 找，再用 major:minor 定位节点。
fn find_metadata_dev() -> Option<String> {
    for p in [
        "/dev/block/by-name/metadata",
        "/dev/block/bootdevice/by-name/metadata",
    ] {
        if std::path::Path::new(p).exists() {
            log::info!("metadata: by-name {}", p);
            return Some(p.to_string());
        }
    }
    if let Ok(entries) = std::fs::read_dir("/sys/class/block") {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            let uev = format!("/sys/class/block/{}/uevent", name);
            let ok = match std::fs::read_to_string(&uev) {
                Ok(s) => s.lines().any(|l| l == "PARTNAME=metadata"),
                Err(_) => false,
            };
            if !ok {
                continue;
            }
            let devfile = format!("/sys/class/block/{}/dev", name);
            if let Ok(dev) = std::fs::read_to_string(&devfile) {
                let d = dev.trim().to_string();
                for cand in [format!("/dev/block/{}", d), format!("/dev/block/{}", name)] {
                    if std::path::Path::new(&cand).exists() {
                        log::info!("metadata: sysfs {} (dev {})", cand, d);
                        return Some(cand);
                    }
                }
            }
        }
    }
    log::error!("metadata: device not found");
    None
}

fn load_module_preferred() -> Result<()> {
    if let Some(dev) = find_metadata_dev() {
        let _ = std::fs::create_dir_all("/mnt/kmeta");
        let c_dev = CString::new(dev)?;
        let c_dir = CString::new("/mnt/kmeta")?;
        let c_fs = CString::new("ext4")?;
        let rc = unsafe {
            mount(
                c_dev.as_ptr(),
                c_dir.as_ptr(),
                c_fs.as_ptr(),
                0,
                std::ptr::null(),
            )
        };
        log::info!("metadata: mount rc={}", rc);
        if rc == 0 {
            let path = "/mnt/kmeta/ksu/kernelsu.ko";
            let sz = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            log::info!("metadata: {} size={}", path, sz);
            if sz > 0 {
                match load_module_from_path(path) {
                    Ok(()) => {
                        log::info!("metadata: override module loaded ({} bytes)", sz);
                        let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
                        return Ok(());
                    }
                    Err(e) => log::error!("metadata: override load failed: {:?}", e),
                }
            }
            let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
        }
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