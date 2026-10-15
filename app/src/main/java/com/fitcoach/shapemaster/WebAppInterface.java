package com.fitcoach.shapemaster;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.Toast;
import androidx.core.app.NotificationCompat;

public class WebAppInterface {
    private final Context context;
    private final WebView webView;
    private static final String CHANNEL_ID = "shapemaster_reminders";

    public WebAppInterface(Context context, WebView webView) {
        this.context = context;
        this.webView = webView;
        createNotificationChannel();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            CharSequence name = "减脂塑形提醒";
            String description = "饮食与训练计划、外卖热量拦截警报";
            int importance = NotificationManager.IMPORTANCE_HIGH;
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, name, importance);
            channel.setDescription(description);
            channel.enableVibration(true);

            NotificationManager notificationManager = context.getSystemService(NotificationManager.class);
            if (notificationManager != null) {
                notificationManager.createNotificationChannel(channel);
            }
        }
    }

    @JavascriptInterface
    public void showToast(String message) {
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show();
    }

    @JavascriptInterface
    public void vibrate(long milliseconds) {
        Vibrator v = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
        if (v != null && v.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(milliseconds, VibrationEffect.DEFAULT_AMPLITUDE));
            } else {
                v.vibrate(milliseconds);
            }
        }
    }

    @JavascriptInterface
    public void playBeep() {
        try {
            ToneGenerator toneGen = new ToneGenerator(AudioManager.STREAM_MUSIC, 100);
            toneGen.startTone(ToneGenerator.TONE_PROP_BEEP, 200);
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public void showNotification(String title, String content) {
        try {
            NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                    .setSmallIcon(android.R.drawable.ic_dialog_alert)
                    .setContentTitle(title)
                    .setContentText(content)
                    .setStyle(new NotificationCompat.BigTextStyle().bigText(content))
                    .setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setAutoCancel(true);

            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify((int) System.currentTimeMillis(), builder.build());
            }
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public void shareText(String title, String text) {
        try {
            Intent sendIntent = new Intent();
            sendIntent.setAction(Intent.ACTION_SEND);
            sendIntent.putExtra(Intent.EXTRA_TEXT, text);
            sendIntent.putExtra(Intent.EXTRA_TITLE, title);
            sendIntent.setType("text/plain");

            Intent shareIntent = Intent.createChooser(sendIntent, title);
            shareIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(shareIntent);
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public void openBrowser(String url) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(context, "无法打开浏览器: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    @JavascriptInterface
    public boolean launchApp(String packageName) {
        try {
            Intent launchIntent = context.getPackageManager().getLaunchIntentForPackage(packageName);
            if (launchIntent != null) {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(launchIntent);
                return true;
            } else {
                String webUrl = packageName.contains("meituan") ? "https://i.meituan.com" : "https://h5.ele.me";
                openBrowser(webUrl);
                return true;
            }
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 版本号一律从 PackageManager 取，不再写死字符串。
     * 旧版这里硬编 "5.0.0"，而 gradle 里是 1.0.0，两处从来没打通——
     * 检查更新必须信得过这个数，所以让它只有一个来源。
     */
    private int selfVersionCode() {
        try {
            android.content.pm.PackageInfo pi = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0);
            // minSdk 24 要兼容，不能用 API 28 才有的 getLongVersionCode()
            return pi != null ? pi.versionCode : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    @JavascriptInterface
    public String getAppVersion() {
        try {
            android.content.pm.PackageInfo pi = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0);
            if (pi != null) {
                return pi.versionName + " (code " + pi.versionCode + ")";
            }
        } catch (Exception ignored) {
        }
        return "未知版本";
    }

    @JavascriptInterface
    public int getAppVersionCode() {
        return selfVersionCode();
    }

    /** 让前端也能主动触发一次检查更新（App 启动时原生也会自己查一遍）。 */
    @JavascriptInterface
    public void checkUpdateNow() {
        if (context instanceof android.app.Activity) {
            ((android.app.Activity) context).runOnUiThread(
                    () -> UpdateManager.check((android.app.Activity) context, true));
        }
    }

    // ================= 第五批：通知权限自检 + 外卖 App 使用情况 =================

    /** 通知到底能不能发。前端拿这个决定是"发通知"还是"页面里提醒"。 */
    @JavascriptInterface
    public boolean notificationsEnabled() {
        try {
            return androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled();
        } catch (Exception e) {
            return false;
        }
    }

    private void openAppSettingsPage() {
        try {
            context.startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    android.net.Uri.parse("package:" + context.getPackageName()))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception ignored) {
            Toast.makeText(context, "打不开系统设置，请手动在设置里找轻塑", Toast.LENGTH_LONG).show();
        }
    }

    /** 跳到本 App 的通知开关（Android 8+ 有直达页，老的退回应用详情页）。 */
    @JavascriptInterface
    public void openNotificationSettings() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, context.getPackageName())
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } else {
                openAppSettingsPage();
            }
        } catch (Exception e) {
            openAppSettingsPage();
        }
    }

    /** 使用情况访问权限是"特殊权限"，不能弹窗申请，只能把人送到设置页自己开。 */
    @JavascriptInterface
    public boolean usageAccessEnabled() {
        try {
            android.app.AppOpsManager aom = (android.app.AppOpsManager)
                    context.getSystemService(Context.APP_OPS_SERVICE);
            if (aom == null) {
                return false;
            }
            int mode;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                mode = aom.unsafeCheckOpNoThrow(android.app.AppOpsManager.OPSTR_GET_USAGE_STATS,
                        android.os.Process.myUid(), context.getPackageName());
            } else {
                mode = aom.checkOpNoThrow(android.app.AppOpsManager.OPSTR_GET_USAGE_STATS,
                        android.os.Process.myUid(), context.getPackageName());
            }
            return mode == android.app.AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    @JavascriptInterface
    public void openUsageAccessSettings() {
        try {
            context.startActivity(new Intent(android.provider.Settings.ACTION_USAGE_ACCESS_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception e) {
            openAppSettingsPage();
        }
    }

    /**
     * 今天这几个外卖 App 被打开过几次、在前台待了多久。
     * 没授权返回 null —— 前端必须显示"未授权"，不能显示 0 次：
     * 0 次的含义是"确实一次都没打开"，那是完全不同的结论。
     */
    @JavascriptInterface
    public String takeoutUsageToday(String packageList) {
        if (!usageAccessEnabled()) {
            return null;
        }
        try {
            android.app.usage.UsageStatsManager usm = (android.app.usage.UsageStatsManager)
                    context.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) {
                return null;
            }
            java.util.Calendar cal = java.util.Calendar.getInstance();
            cal.set(java.util.Calendar.HOUR_OF_DAY, 0);
            cal.set(java.util.Calendar.MINUTE, 0);
            cal.set(java.util.Calendar.SECOND, 0);
            cal.set(java.util.Calendar.MILLISECOND, 0);
            long begin = cal.getTimeInMillis();
            long now = System.currentTimeMillis();

            java.util.List<String> pkgs = new java.util.ArrayList<String>();
            for (String p : packageList.split(",")) {
                String t = p.trim();
                if (t.length() > 0) {
                    pkgs.add(t);
                }
            }
            java.util.Map<String, long[]> agg = new java.util.LinkedHashMap<String, long[]>();
            for (String p : pkgs) {
                agg.put(p, new long[]{0L, 0L});
            }

            android.app.usage.UsageEvents ev = usm.queryEvents(begin, now);
            if (ev != null) {
                android.app.usage.UsageEvents.Event e = new android.app.usage.UsageEvents.Event();
                String activePkg = null;
                long activeAt = 0L;
                while (ev.hasNextEvent()) {
                    ev.getNextEvent(e);
                    long[] cell = agg.get(e.getPackageName());
                    if (cell == null) {
                        continue;
                    }
                    int type = e.getEventType();
                    if (type == android.app.usage.UsageEvents.Event.ACTIVITY_RESUMED) {
                        cell[0] += 1L;
                        activePkg = e.getPackageName();
                        activeAt = e.getTimeStamp();
                    } else if (type == android.app.usage.UsageEvents.Event.ACTIVITY_PAUSED
                            || type == android.app.usage.UsageEvents.Event.ACTIVITY_STOPPED) {
                        if (activePkg != null && activePkg.equals(e.getPackageName())
                                && e.getTimeStamp() > activeAt) {
                            cell[1] += (e.getTimeStamp() - activeAt);
                            activeAt = e.getTimeStamp();
                        }
                    }
                }
            }

            org.json.JSONArray arr = new org.json.JSONArray();
            for (java.util.Map.Entry<String, long[]> en : agg.entrySet()) {
                org.json.JSONObject o = new org.json.JSONObject();
                o.put("pkg", en.getKey());
                o.put("launches", en.getValue()[0]);
                o.put("foregroundMs", en.getValue()[1]);
                arr.put(o);
            }
            org.json.JSONObject top = new org.json.JSONObject();
            top.put("granted", true);
            top.put("since", begin);
            top.put("apps", arr);
            return top.toString();
        } catch (Exception ex) {
            return null;
        }
    }

    /** 发一条通知；没权限时不发并返回 false，让前端改用页面内提醒。 */
    @JavascriptInterface
    public boolean tryNotify(String title, String content) {
        if (!notificationsEnabled()) {
            return false;
        }
        try {
            showNotification(title, content);
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
