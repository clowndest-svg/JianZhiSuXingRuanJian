package com.fitcoach.shapemaster;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 检查线上 APK 是否更新。
 * <p>
 * 为什么不让前端做：前端跑在 WebView 里，页面本身加载失败时（旧版缓存、断网半截）
 * 就永远没机会提醒更新，而那恰恰是最需要提醒的时候。所以启动时在原生层查一遍。
 * <p>
 * 只提醒、不静默安装：下载交给系统浏览器/下载器，用户自己走安装流程。
 * 装不了新版本这件事必须由用户决定，App 不替他点。
 */
public final class UpdateManager {

    private static final String MANIFEST_URL = BuildConfig.API_BASE_URL + "/version.json";
    private static final String PREFS = "update_prompt";
    private static final Handler UI = new Handler(Looper.getMainLooper());

    private UpdateManager() {
    }

    public static void check(final Activity act, final boolean manual) {
        if (act == null) {
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String json = fetch();
                UI.post(new Runnable() {
                    @Override
                    public void run() {
                        decide(act, json, manual);
                    }
                });
            }
        }, "qingsu-update").start();
    }

    private static String fetch() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(MANIFEST_URL).openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(8000);
            c.setRequestProperty("Cache-Control", "no-cache");
            c.setRequestMethod("GET");
            if (c.getResponseCode() != 200) {
                return null;
            }
            InputStream in = c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    private static void decide(Activity act, String json, boolean manual) {
        if (act.isFinishing() || act.isDestroyed()) return;
        if (json == null) {
            if (manual) {
                Toast.makeText(act, "没连上更新服务器，检查不了新版本", Toast.LENGTH_LONG).show();
            }
            return;
        }
        int remote;
        String name, apk, notes;
        long size;
        try {
            JSONObject o = new JSONObject(json);
            remote = o.optInt("version_code", 0);
            name = o.optString("version_name", "");
            apk = o.optString("apk_url", "/qingsu.apk");
            notes = o.optString("notes", "");
            size = o.optLong("size", 0L);
        } catch (Exception e) {
            if (manual) {
                Toast.makeText(act, "版本清单读不懂，没当成有更新", Toast.LENGTH_LONG).show();
            }
            return;
        }
        int mine = mine(act);
        if (remote <= 0 || remote <= mine) {
            if (manual) {
                Toast.makeText(act, "已经是最新版（" + mine + "）", Toast.LENGTH_LONG).show();
            }
            return;
        }
        SharedPreferences sp = act.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!manual && sp.getInt("skipped", 0) == remote) {
            return;                     // 这一版用户刚点过"这次不更新"
        }
        final String url = apk.startsWith("http") ? apk : "https://124.220.54.64" + apk;
        Uri downloadUri = Uri.parse(url);
        if (!("https".equals(downloadUri.getScheme()) || "http".equals(downloadUri.getScheme()))
                || !"124.220.54.64".equals(downloadUri.getHost())) return;
        String mb = size > 0 ? String.format(java.util.Locale.CHINA, "%.1f MB", size / 1048576.0) : "未知大小";
        final int r = remote;
        TextView body = new TextView(act);
        body.setText(UpdateCopy.body(mine, r, mb, notes));
        body.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f);
        body.setTextColor(0xFF0F172A);
        float density = act.getResources().getDisplayMetrics().density;
        body.setLineSpacing(6f * density, 1.08f);
        body.setPadding((int) (24 * density), (int) (10 * density),
                (int) (24 * density), (int) (6 * density));
        new android.app.AlertDialog.Builder(act)
                .setTitle("发现新版本 " + (name.isEmpty() ? r : name))
                .setView(body)
                .setPositiveButton("去下载", (d, w) -> {
                    try {
                        Intent it = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        act.startActivity(it);
                    } catch (Exception e) {
                        Toast.makeText(act, "打不开下载链接：" + url, Toast.LENGTH_LONG).show();
                    }
                })
                .setNeutralButton("这次不更新", (d, w) -> sp.edit().putInt("skipped", r).apply())
                .setCancelable(true)
                .show();
    }

    private static int mine(Context c) {
        try {
            android.content.pm.PackageInfo pi = c.getPackageManager()
                    .getPackageInfo(c.getPackageName(), 0);
            if (pi == null) {
                return 0;
            }
            // minSdk 24 要兼容，不能用 API 28 才有的 getLongVersionCode()
            return pi.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }
}
