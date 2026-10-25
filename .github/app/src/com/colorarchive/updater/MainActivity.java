package com.colorarchive.updater;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final String REPO = "one899/android_kernel_oneplus_sm8350_9rt_295bpf";
    private static final String TAG = "lkm-latest";
    private static final String META = "/metadata/ksu/kernelsu.ko";

    private TextView status;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile String lastKoUrl = null;
    private volatile String lastBootUrl = null;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int p = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(p, p, p, p);

        TextView title = new TextView(this);
        title.setText("ColorArchive LKM 更新器");
        title.setTextSize(20);
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(13);
        status.setPadding(0, p, 0, p);
        root.addView(status);

        root.addView(btn("① 更新模块 (.ko 热更新)", new Runnable() {
            public void run() { downloadKo(); }
        }));
        root.addView(btn("② 下载最新 boot 镜像", new Runnable() {
            public void run() { downloadBoot(); }
        }));
        root.addView(btn("③ 重启设备", new Runnable() {
            public void run() { execRoot("reboot"); }
        }));
        root.addView(btn("刷新状态", new Runnable() {
            public void run() { refresh(); }
        }));

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
        refresh();
    }

    private Button btn(String text, final Runnable action) {
        Button b = new Button(this);
        b.setText(text);
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                new Thread(action).start();
            }
        });
        return b;
    }

    private void toast(final String msg) {
        ui.post(new Runnable() {
            public void run() { status.setText(msg); }
        });
    }

    private void refresh() {
        new Thread(new Runnable() {
            public void run() {
                StringBuilder sb = new StringBuilder();
                sb.append("内核: ").append(System.getProperty("os.version")).append("\n");
                sb.append("模块: ");
                String mods = readFile("/proc/modules");
                boolean loaded = mods != null && mods.contains("kernelsu");
                sb.append(loaded ? "已加载" : "未加载").append("\n");
                File f = new File(META);
                if (f.exists()) {
                    sb.append("热更新: 已放置 (").append(f.length()).append(" 字节)\n");
                } else {
                    sb.append("热更新: 未放置（使用 ramdisk 内置）\n");
                }
                String df = exec("sh -c 'df -h /metadata 2>/dev/null | tail -1'");
                if (df != null && df.length() > 0) sb.append("metadata: ").append(df).append("\n");
                String root = execRoot("id");
                sb.append("root: ").append(root != null && root.contains("uid=0") ? "可用" : "不可用").append("\n");
                toast(sb.toString());
            }
        }).start();
    }

    private String readFile(String path) {
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(new java.io.FileInputStream(path)));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
            r.close();
            return sb.toString();
        } catch (Exception e) { return null; }
    }

    private String execRoot(String cmd) {
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"su", "-c", cmd});
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
            p.waitFor();
            return sb.toString().trim();
        } catch (Exception e) { return null; }
    }

    private String exec(String cmd) {
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"sh", "-c", cmd});
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
            p.waitFor();
            return sb.toString().trim();
        } catch (Exception e) { return null; }
    }

    private String fetchReleaseJson() {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(
                    "https://api.github.com/repos/" + REPO + "/releases/tags/" + TAG).openConnection();
            c.setRequestProperty("Accept", "application/vnd.github+json");
            c.setConnectTimeout(15000);
            c.setReadTimeout(30000);
            if (c.getResponseCode() != 200) return null;
            InputStream in = c.getInputStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Exception e) { return null; }
    }

    private void ensureAssetUrls() {
        if (lastKoUrl != null && lastBootUrl != null) return;
        String json = fetchReleaseJson();
        if (json == null) { toast("拉取 release 失败（网络或 release 不存在）"); return; }
        Matcher m = Pattern.compile("\"browser_download_url\"\\s*:\\s*\"([^\"]+)\"").matcher(json);
        while (m.find()) {
            String u = m.group(1);
            if (u.endsWith(".ko") && lastKoUrl == null) lastKoUrl = u;
            if (u.contains("boot-lkm") && u.endsWith(".img") && lastBootUrl == null) lastBootUrl = u;
        }
    }

    private File download(String url, String name) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(120000);
        c.setInstanceFollowRedirects(true);
        File out = new File(getCacheDir(), name);
        InputStream in = c.getInputStream();
        FileOutputStream fo = new FileOutputStream(out);
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) fo.write(buf, 0, n);
        fo.close();
        in.close();
        return out;
    }

    private void downloadKo() {
        ensureAssetUrls();
        if (lastKoUrl == null) { toast("未找到 .ko 资源"); return; }
        toast("下载模块中...\n" + lastKoUrl);
        try {
            File ko = download(lastKoUrl, "kernelsu.ko");
            String cmd = "mkdir -p /metadata/ksu && cp -f '" + ko.getAbsolutePath()
                    + "' '" + META + "' && chmod 644 '" + META + "' && sync && ls -l '" + META + "'";
            String res = execRoot(cmd);
            if (res == null || !res.contains("kernelsu.ko")) {
                toast("写入失败。可能 /metadata 空间不足。\n" + (res == null ? "" : res));
                return;
            }
            ui.post(new Runnable() {
                public void run() {
                    new AlertDialog.Builder(MainActivity.this)
                            .setTitle("完成")
                            .setMessage("模块已写入 /metadata/ksu/kernelsu.ko\n重启后生效")
                            .setPositiveButton("立即重启", new DialogInterface.OnClickListener() {
                                public void onClick(DialogInterface d, int w) { execRoot("reboot"); }
                            })
                            .setNegativeButton("稍后", null)
                            .show();
                }
            });
            toast("已写入:\n" + res);
        } catch (Exception e) {
            toast("下载/写入异常: " + e);
        }
    }

    private void downloadBoot() {
        ensureAssetUrls();
        if (lastBootUrl == null) { toast("未找到 boot 资源"); return; }
        toast("下载 boot 中...\n" + lastBootUrl);
        try {
            File img = download(lastBootUrl, "boot.img");
            String name = "boot-lkm-9rt-latest.img";
            String cp = "cp -f '" + img.getAbsolutePath() + "' /sdcard/Download/" + name
                    + " && ls -l /sdcard/Download/" + name;
            String res = exec(cp);
            toast("已保存到 /sdcard/Download/" + name + "\n\n" + res
                    + "\n\n电脑上执行:\n adb reboot bootloader\n fastboot flash boot_a " + name
                    + "\n fastboot reboot");
        } catch (Exception e) {
            toast("下载异常: " + e);
        }
    }
}