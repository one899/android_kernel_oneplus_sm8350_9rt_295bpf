#!/usr/bin/env python3
"""ksuinit 诊断版：只挂 sysfs + 列出候选分区，不做任何分区挂载，确保能开机。"""
import sys

HELPER = r'''

// ==== ColorArchive: 诊断版（只探测，不挂载分区）====
fn mount_sysfs() -> bool {
    let _ = std::fs::create_dir_all("/mnt/ksys");
    let c_src = CString::new("sysfs").unwrap();
    let c_dir = CString::new("/mnt/ksys").unwrap();
    let c_fs = CString::new("sysfs").unwrap();
    let rc = unsafe { mount(c_src.as_ptr(), c_dir.as_ptr(), c_fs.as_ptr(), 1, std::ptr::null()) };
    log::info!("diag: sysfs mount rc={}", rc);
    rc == 0 || std::path::Path::new("/mnt/ksys/class/block").exists()
}

fn diag_list_partitions() {
    let rd = match std::fs::read_dir("/mnt/ksys/class/block") {
        Ok(r) => r,
        Err(e) => {
            log::error!("diag: read_dir failed {:?}", e);
            return;
        }
    };
    let mut total = 0;
    let mut hit = 0;
    for e in rd.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        let base = format!("/mnt/ksys/class/block/{}", name);
        let uev = std::fs::read_to_string(format!("{}/uevent", base)).unwrap_or_default();
        if !uev.lines().any(|l| l == "DEVTYPE=partition") {
            continue;
        }
        total += 1;
        let sectors: u64 = std::fs::read_to_string(format!("{}/size", base))
            .ok()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);
        let mb = sectors / 2048;
        if mb >= 4 && mb <= 96 {
            hit += 1;
            let devname = uev
                .lines()
                .find_map(|l| l.strip_prefix("DEVNAME="))
                .unwrap_or("?");
            log::info!("diag: candidate {} {}MB dev={}", name, mb, devname);
        }
    }
    log::info!("diag: partitions total={} candidates={}", total, hit);
}

fn load_module_preferred() -> Result<()> {
    if mount_sysfs() {
        diag_list_partitions();
    }
    log::info!("diag: fallback to ramdisk /kernelsu.ko");
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