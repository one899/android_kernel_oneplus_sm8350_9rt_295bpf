#!/system/bin/sh
# ColorArchive LKM 更新工具 (ccupdate)
# 用法: sh ccupdate.sh
REPO="one899/android_kernel_oneplus_sm8350_9rt_295bpf"
TAG="lkm-latest"
API="https://api.github.com/repos/$REPO/releases/tags/$TAG"
TMP="/data/local/tmp/ccupdate"
META="/metadata/ksu/kernelsu.ko"

say() { echo "$@"; }
die() { echo "错误: $*"; exit 1; }

need_root() {
  if ! su -c "id" 2>/dev/null | grep -q "uid=0"; then
    die "需要 root（KernelSU 已授权本终端）"
  fi
}

asset_url() {
  curl -fsSL "$API" 2>/dev/null | grep -o "\"browser_download_url\": *\"[^\"]*$1[^\"]*\"" | head -1 | sed 's/.*"\(http[^"]*\)"/\1/'
}

show_status() {
  echo "=== 当前状态 ==="
  KREL=$(uname -r)
  echo "内核    : $KREL"
  if grep -q kernelsu /proc/modules 2>/dev/null; then
    echo "模块    : 已加载"
  else
    echo "模块    : 未加载"
  fi
  if [ -f "$META" ]; then
    echo "热更新  : 已放置 ($(ls -l "$META" | awk '{print $5}') 字节)"
  else
    echo "热更新  : 未放置（使用 ramdisk 内置版本）"
  fi
  df -h /metadata 2>/dev/null | tail -1 | awk '{print "metadata: 可用 "$4}'
}

update_ko() {
  need_root
  mkdir -p "$TMP"
  URL=$(asset_url "kernelsu-stripped.ko")
  [ -z "$URL" ] && URL=$(asset_url ".ko")
  [ -z "$URL" ] && die "未在 release 里找到 .ko"
  say "下载: $URL"
  curl -fL --progress-bar -o "$TMP/kernelsu.ko" "$URL" || die "下载失败"
  SZ=$(ls -l "$TMP/kernelsu.ko" | awk '{print $5}')
  say "大小: $SZ 字节"
  FREE=$(df /metadata 2>/dev/null | tail -1 | awk '{print $4}')
  if [ -n "$FREE" ] && [ "$SZ" -gt $((FREE * 1024)) ] 2>/dev/null; then
    die "/metadata 空间不足（剩余 $((FREE/1024)) MB，需要 $((SZ/1048576)) MB）"
  fi
  su -c "mkdir -p /metadata/ksu && cp -f '$TMP/kernelsu.ko' '$META' && chmod 644 '$META' && sync" || die "写入 /metadata 失败"
  say "已写入 $META"
  say ""
  say "重启后生效。是否现在重启？(y/N)"
  read ans
  case "$ans" in y|Y) su -c "reboot" ;; *) say "稍后手动重启即可" ;; esac
}

update_boot() {
  mkdir -p /sdcard/Download
  URL=$(asset_url "boot-lkm-9rt")
  [ -z "$URL" ] && die "未在 release 里找到 boot 镜像"
  NAME=$(basename "$URL")
  say "下载: $URL"
  curl -fL --progress-bar -o "/sdcard/Download/$NAME" "$URL" || die "下载失败"
  SUM_URL=$(asset_url "SHA256SUMS")
  if [ -n "$SUM_URL" ]; then
    curl -fsSL -o "$TMP/SHA256SUMS" "$SUM_URL" 2>/dev/null
    EXPECTED=$(grep " $NAME\$" "$TMP/SHA256SUMS" 2>/dev/null | awk '{print $1}')
    if [ -n "$EXPECTED" ]; then
      ACTUAL=$(sha256sum "/sdcard/Download/$NAME" | awk '{print $1}')
      [ "$EXPECTED" = "$ACTUAL" ] || die "校验失败: 期望 $EXPECTED 实际 $ACTUAL"
      say "SHA256 校验通过"
    fi
  fi
  say ""
  say "文件已保存: /sdcard/Download/$NAME"
  say ""
  say "刷写步骤（电脑上执行）:"
  say "  1. adb reboot bootloader"
  say "  2. fastboot flash boot_a $NAME"
  say "  3. fastboot reboot"
  say ""
  say "或者本机有 fastboot 的话:"
  say "  su -c 'reboot bootloader'"
}

echo "================================"
echo "  ColorArchive LKM 更新工具"
echo "================================"
echo "1) 更新内核模块 (.ko 热更新，重启生效)"
echo "2) 下载最新 boot 镜像 (整包刷写)"
echo "3) 查看当前状态"
echo "0) 退出"
echo ""
printf "选择: "
read choice
case "$choice" in
  1) update_ko ;;
  2) update_boot ;;
  3) show_status ;;
  *) exit 0 ;;
esac