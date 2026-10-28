package com.fitcoach.shapemaster;

import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.Toast;
import androidx.core.app.NotificationCompat;

public class WebAppInterface {
    private final java.util.concurrent.ThreadPoolExecutor LOCAL_AI = new java.util.concurrent.ThreadPoolExecutor(
            2, 2, 0L, java.util.concurrent.TimeUnit.MILLISECONDS,
            new java.util.concurrent.ArrayBlockingQueue<>(4));
    private final Context context;
    private final WebView webView;
    private static final String CHANNEL_ID = "shapemaster_reminders";
    private AudioManager audioManager;
    private AudioFocusRequest audioFocusRequest;

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
    public String microphonePermissionState() {
        return context instanceof MainActivity ? ((MainActivity) context).microphonePermissionState() : "unknown";
    }

    @JavascriptInterface
    public void requestMicrophonePermission() {
        if (context instanceof MainActivity) ((MainActivity) context).runOnUiThread(
                () -> ((MainActivity) context).requestMicPreflight());
    }

    @JavascriptInterface
    public void openAppSettings() {
        openAppSettingsPage();
    }

    @JavascriptInterface
    public void startVoiceCallAudio(boolean speaker) {
        if (!(context instanceof Activity)) return;
        Activity activity = (Activity) context;
        activity.runOnUiThread(() -> {
            try {
                if (audioManager == null) audioManager = (AudioManager) activity.getSystemService(Context.AUDIO_SERVICE);
                if (audioManager != null) {
                    audioManager.setMode(AudioManager.MODE_IN_COMMUNICATION);
                    audioManager.setSpeakerphoneOn(speaker);
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        AudioAttributes attrs = new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
                        audioFocusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                                .setAudioAttributes(attrs).build();
                        audioManager.requestAudioFocus(audioFocusRequest);
                    } else {
                        audioManager.requestAudioFocus(null, AudioManager.STREAM_VOICE_CALL,
                                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);
                    }
                }
                activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            } catch (Exception ignored) {
                // Audio routing is best-effort; WebRTC still carries the call.
            }
        });
    }

    @JavascriptInterface
    public void setVoiceCallSpeaker(boolean speaker) {
        if (!(context instanceof Activity)) return;
        Activity activity = (Activity) context;
        activity.runOnUiThread(() -> {
            try {
                if (audioManager == null) audioManager = (AudioManager) activity.getSystemService(Context.AUDIO_SERVICE);
                if (audioManager != null) audioManager.setSpeakerphoneOn(speaker);
            } catch (Exception ignored) {
            }
        });
    }

    @JavascriptInterface
    public void stopVoiceCallAudio() {
        if (!(context instanceof Activity)) return;
        Activity activity = (Activity) context;
        activity.runOnUiThread(() -> {
            try {
                if (audioManager == null) audioManager = (AudioManager) activity.getSystemService(Context.AUDIO_SERVICE);
                if (audioManager != null) {
                    audioManager.setSpeakerphoneOn(false);
                    audioManager.setMode(AudioManager.MODE_NORMAL);
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        if (audioFocusRequest != null) audioManager.abandonAudioFocusRequest(audioFocusRequest);
                        audioFocusRequest = null;
                    } else {
                        audioManager.abandonAudioFocus(null);
                    }
                }
                activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            } catch (Exception ignored) {
            }
        });
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
            new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(toneGen::release, 250);
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public void showNotification(String title, String content) {
        try {
            NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                    .setSmallIcon(R.drawable.ic_stat_qingsu)
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
            android.net.Uri parsed = android.net.Uri.parse(url);
            if (!"https".equals(parsed.getScheme()) && !"http".equals(parsed.getScheme())) return;
            Intent intent = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(context, "无法打开浏览器: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    @JavascriptInterface
    public void searchDouyin(String keyword) {
        if (keyword == null || keyword.trim().isEmpty() || keyword.length() > 200) return;
        final String query = keyword.trim();
        final String packageName = "com.ss.android.ugc.aweme";
        try {
            // Package visibility is declared explicitly for Android 11+.
            context.getPackageManager().getPackageInfo(packageName, 0);
            android.net.Uri uri = new android.net.Uri.Builder().scheme("snssdk1128")
                    .authority("search").appendQueryParameter("keyword", query).build();
            Intent search = new Intent(Intent.ACTION_VIEW, uri).setPackage(packageName);
            search.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (search.resolveActivity(context.getPackageManager()) != null) {
                context.startActivity(search);
                return;
            }
        } catch (Exception ignored) {
            // Missing, disabled, or incompatible Douyin: retain the same search on the web.
        }
        openBrowser("https://www.douyin.com/search/" + android.net.Uri.encode(query) + "?type=video");
    }

    @JavascriptInterface
    public boolean launchApp(String packageName) {
        if (!"com.sankuai.meituan".equals(packageName) && !"me.ele".equals(packageName)) return false;
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

    @JavascriptInterface public String reminderStatus() {
        android.content.SharedPreferences p=context.getSharedPreferences("reminders",Context.MODE_PRIVATE);
        return "{\"enabled\":"+p.getBoolean("enabled",false)+",\"hour\":"+p.getInt("hour",20)+",\"minute\":"+p.getInt("minute",0)+"}";
    }
    @JavascriptInterface public void saveCsv(String content) {
        if(context instanceof MainActivity)((MainActivity)context).saveCsv(content);
    }
    @JavascriptInterface public void savePng(String dataUrl) {
        if(context instanceof MainActivity)((MainActivity)context).savePng(dataUrl);
    }
    @JavascriptInterface public String getApiBase() {return BuildConfig.API_BASE_URL;}
    @JavascriptInterface public void localAiRequest(String id,int port,String endpoint,String body) {
        if(webView==null || id==null || id.length()>100 || port<1024 || port>65535
                || !("/health".equals(endpoint)||"/v1/chat/completions".equals(endpoint)) || (body!=null && body.length()>30000))return;
        try { LOCAL_AI.execute(()->{
            org.json.JSONObject result=new org.json.JSONObject();java.net.HttpURLConnection connection=null;
            try{
                connection=(java.net.HttpURLConnection)new java.net.URL("http://127.0.0.1:"+port+endpoint).openConnection();
                connection.setConnectTimeout(1500);connection.setReadTimeout(25000);connection.setInstanceFollowRedirects(false);
                if(body!=null && !body.isEmpty()){
                    connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");
                    try(java.io.OutputStream out=connection.getOutputStream()){out.write(body.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
                }
                int status=connection.getResponseCode();result.put("status",status);
                java.io.InputStream source=status>=400?connection.getErrorStream():connection.getInputStream();
                java.io.ByteArrayOutputStream output=new java.io.ByteArrayOutputStream();
                if(source!=null)try(java.io.InputStream in=source){byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))!=-1){if(output.size()+n>256*1024)throw new java.io.IOException("Response too large");output.write(buffer,0,n);}}
                result.put("body",output.toString("UTF-8"));
            }catch(Exception e){try{result.put("error",e.getClass().getSimpleName());}catch(Exception ignored){}}
            finally{if(connection!=null)connection.disconnect();}
            String script="if(window.onLocalAiResponse)window.onLocalAiResponse("+org.json.JSONObject.quote(id)+","+result.toString()+");";
            webView.post(()->{if(context instanceof android.app.Activity && ((android.app.Activity)context).isDestroyed())return;webView.evaluateJavascript(script,null);});
        }); } catch (java.util.concurrent.RejectedExecutionException busy) {
            String script="window.onLocalAiResponse&&window.onLocalAiResponse("+org.json.JSONObject.quote(id)+",{error:'busy'});";
            webView.post(() -> { if (context instanceof Activity && !((Activity) context).isDestroyed()) webView.evaluateJavascript(script,null); });
        }
    }
    public void release() {
        LOCAL_AI.shutdownNow();
        stopVoiceCallAudio();
    }
    @JavascriptInterface public boolean configureReminder(boolean enabled,int hour,int minute) {
        if(hour<0||hour>23||minute<0||minute>59)return false;
        context.getSharedPreferences("reminders",Context.MODE_PRIVATE).edit().putBoolean("enabled",enabled).putInt("hour",hour).putInt("minute",minute).apply();
        ReminderReceiver.schedule(context);return true;
    }
}
