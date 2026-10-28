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
    private static final java.util.Map<Activity, Boolean> CHECKS = new java.util.WeakHashMap<>();

    private UpdateManager() {
    }

    public static void check(final Activity act, final boolean manual) {
        if (act == null) {
            return;
        }
        synchronized (CHECKS) {
            if (CHECKS.containsKey(act)) { CHECKS.put(act, CHECKS.get(act) || manual); return; }
            CHECKS.put(act, manual);
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String json = fetch();
                UI.post(new Runnable() {
                    @Override
                    public void run() {
                        boolean showManual;
                        synchronized (CHECKS) { showManual = Boolean.TRUE.equals(CHECKS.remove(act)); }
                        decide(act, json, showManual);
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
            c.setRequestProperty("X-App-Build", String.valueOf(BuildConfig.VERSION_CODE));
            c.setRequestMethod("GET");
            if (c.getResponseCode() != 200) {
                return null;
            }
            InputStream in = c.getInputStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                if (bo.size() + n > 256 * 1024) { in.close(); return null; }
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
        final String url = apk.startsWith("http") ? apk : BuildConfig.API_BASE_URL + apk;
        Uri downloadUri = Uri.parse(url);
        if (!"https".equals(downloadUri.getScheme())
                || !("124.220.54.64".equals(downloadUri.getHost())
                    || "scientificexploration.art".equals(downloadUri.getHost()))
                || downloadUri.getUserInfo() != null
                || (downloadUri.getPort() != -1 && downloadUri.getPort() != 443)) return;
        String mb = size > 0 ? String.format(java.util.Locale.CHINA, "%.1f MB", size / 1048576.0) : "未知大小";
        final int r = remote;
        showUpdateDialog(act, "发现新版本 " + (name.isEmpty() ? r : name),
                UpdateCopy.body(mine, r, mb, notes),
                new Runnable() {
                    @Override
                    public void run() {
                        try {
                            Intent it = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                            act.startActivity(it);
                        } catch (Exception e) {
                            Toast.makeText(act, "打不开下载链接：" + url, Toast.LENGTH_LONG).show();
                        }
                    }
                },
                new Runnable() {
                    @Override
                    public void run() {
                        sp.edit().putInt("skipped", r).apply();
                    }
                });
    }

    /**
     * 更新弹窗。高度封顶只能加在滚动容器上：加在 TextView 上，文本会自己裁掉、
     * ScrollView 永远撑不满，于是"能上下滑"是假的——r174 就是这么漏过一次，
     * 机主 10-22 实拍长说明仍然被吃掉半行。
     */
    static android.app.AlertDialog showUpdateDialog(Activity act, String title, CharSequence message,
                                                    final Runnable onDownload, final Runnable onSkip) {
        float density = act.getResources().getDisplayMetrics().density;
        TextView body = new TextView(act);
        body.setText(message);
        body.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f);
        body.setTextColor(0xFF0F172A);
        body.setLineSpacing(6f * density, 1.08f);
        body.setPadding((int) (24 * density), (int) (10 * density),
                (int) (24 * density), (int) (6 * density));
        int maxPx = Math.round(act.getResources().getDisplayMetrics().heightPixels * 0.52f);
        ScrollCap scroll = new ScrollCap(act, maxPx);
        scroll.addView(body, new android.widget.FrameLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                android.view.ViewGroup.LayoutParams.WRAP_CONTENT));
        final android.app.AlertDialog dialog = new android.app.AlertDialog.Builder(act)
                .setTitle(title)
                .setView(scroll)
                .setPositiveButton("去下载", null)
                .setNeutralButton("这次不更新", null)
                .setCancelable(true)
                .create();
        dialog.show();
        // show() 之后按钮才存在；自己接管点击，免得 dismiss 与回调顺序说不清
        android.widget.Button go = dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE);
        android.widget.Button skip = dialog.getButton(android.app.AlertDialog.BUTTON_NEUTRAL);
        if (go != null) {
            go.setOnClickListener(v -> {
                dialog.dismiss();
                onDownload.run();
            });
        }
        if (skip != null) {
            skip.setOnClickListener(v -> {
                dialog.dismiss();
                onSkip.run();
            });
        }
        return dialog;
    }

    /** 说明超过屏幕一半时自己封顶，剩下的交给滑动；滚动条常显，让人看得出还能滑。 */
    static final class ScrollCap extends android.widget.ScrollView {
        private final int maxPx;

        ScrollCap(Context c, int maxPx) {
            super(c);
            this.maxPx = maxPx;
            setVerticalScrollBarEnabled(true);
            setScrollbarFadingEnabled(false);
        }

        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            super.onMeasure(widthSpec, android.view.View.MeasureSpec.makeMeasureSpec(
                    maxPx, android.view.View.MeasureSpec.AT_MOST));
        }
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
