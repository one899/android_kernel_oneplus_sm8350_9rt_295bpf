#!/usr/bin/env python3
"""给 ksuinit 打补丁：优先从 /metadata/ksu/kernelsu.ko 加载，实现 .ko 热更新。

用法: python3 ksuinit_override.py <path/to/userspace/ksuinit/src/init.rs>
"""
import sys

HELPER = r'''

// ==== ColorArchive: .ko 热更新支持 ====
// 优先从 /metadata（未加密）加载模块；失败回退 ramdisk 的 /kernelsu.ko
fn load_module_preferred() -> Result<()> {
    let devs = [
        "/dev/block/by-name/metadata",
        "/dev/block/bootdevice/by-name/metadata",
    ];
    for dev in devs {
        if !std::path::Path::new(dev).exists() {
            continue;
        }
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
        if rc != 0 {
            log::error!("mount {} failed: rc={}", dev, rc);
            continue;
        }
        let path = "/mnt/kmeta/ksu/kernelsu.ko";
        let exists = std::path::Path::new(path).exists();
        if exists {
            log::info!("found override module: {}", path);
            match load_module_from_path(path) {
                Ok(()) => {
                    log::info!("override module loaded");
                    let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
                    return Ok(());
                }
                Err(e) => log::error!("override load failed: {:?}", e),
            }
        } else {
            log::info!("no override module at {}", path);
        }
        let _ = unmount("/mnt/kmeta", UnmountFlags::DETACH);
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
        print("!! anchor not found:", old)
        return 1

    src = src.replace(old, new, 1)
    src = src + HELPER
    open(path, "w", encoding="utf-8").write(src)
    print("patched:", path)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "userspace/ksuinit/src/init.rs"))