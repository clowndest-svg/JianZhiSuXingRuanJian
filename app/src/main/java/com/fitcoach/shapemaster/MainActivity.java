package com.fitcoach.shapemaster;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.webkit.ValueCallback;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebResourceError;
import androidx.webkit.WebViewAssetLoader;
import android.widget.Toast;

public class MainActivity extends Activity {

    private static final int FILE_CHOOSER_REQUEST_CODE = 1001;
    private ValueCallback<Uri[]> filePathCallback;
    private WebView webView;
    private WebAppInterface androidBridge;
    private final java.util.concurrent.ExecutorService exports = java.util.concurrent.Executors.newSingleThreadExecutor();
    private boolean exportBusy;
    private long backPressedTime = 0;
    private Uri cameraUri;
    private String pendingExport;
    private byte[] pendingPng;
    private static final int PNG_EXPORT_REQUEST = 2027;

    public void savePng(String dataUrl) {
        if (dataUrl == null || !dataUrl.startsWith("data:image/png;base64,") || dataUrl.length() > 4000000) return;
        final byte[] png;
        try { png = android.util.Base64.decode(dataUrl.substring(22), android.util.Base64.DEFAULT); }
        catch (IllegalArgumentException e) { return; }
        if (png.length < 8 || png[0] != (byte)137 || png[1] != 80 || png[2] != 78 || png[3] != 71) return;
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed() || exportBusy || pendingPng != null || pendingExport != null) return;
            pendingPng = png;
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("image/png").putExtra(Intent.EXTRA_TITLE, "轻塑记录回顾.png");
            try { startActivityForResult(intent, PNG_EXPORT_REQUEST); }
            catch (Exception e) { pendingPng = null; Toast.makeText(this, "无法打开图片保存位置", Toast.LENGTH_LONG).show(); }
        });
    }
    private static final int SAVE_CSV_REQUEST = 1002;

    public void saveCsv(String content) {
        if(content==null || content.length()>5*1024*1024) return;
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed() || exportBusy || pendingExport != null || pendingPng != null) return;
            pendingExport=content;
            Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("text/csv").putExtra(Intent.EXTRA_TITLE,"轻塑记录.csv");
            try {startActivityForResult(intent,SAVE_CSV_REQUEST);}
            catch(Exception e){pendingExport=null;Toast.makeText(this,"无法打开保存位置",Toast.LENGTH_LONG).show();}
        });
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Customize status bar color to fresh light background with dark icons
        Window window = getWindow();
        {
            window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS);
            window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            window.setStatusBarColor(Color.parseColor("#F8FAFC"));
        }
        {
            window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }

        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMediaPlaybackRequiresUserGesture(false);
        // H5 的 navigator.geolocation 要这条，否则页面里调它永远直接报错
        settings.setGeolocationEnabled(true);

        // Bridge interface for native notifications, vibration and audio cues
        androidBridge = new WebAppInterface(this, webView);
        webView.addJavascriptInterface(androidBridge, "AndroidBridge");

        // HTTPS assets and API share the secure transport policy.
        final WebViewAssetLoader assets = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assets.shouldInterceptRequest(request.getUrl());
            }
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("https".equals(uri.getScheme()) && "appassets.androidplatform.net".equals(uri.getHost())) return false;
                if ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (Exception ignored) { }
                }
                return true;
            }
            // 断网时 WebView 会自己画一张"网页无法打开"，同样把内置页地址（appassets…）当标题写出来。
            // 换成应用自己的离线页：说人话、给重试，也不把内部地址露给用户。
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request == null || !request.isForMainFrame()) return;
                String failed = String.valueOf(request.getUrl());
                // 离线页自己都加载失败时别再套娃，否则会无限重定向
                if (failed.contains("/assets/offline.html")) return;
                view.loadUrl("https://appassets.androidplatform.net/assets/offline.html?retry="
                        + Uri.encode(failed));
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            // WebChromeClient 的授权回调在 UI 线程，和系统权限结果、生命周期串行处理。
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                handleMediaPermissionRequest(request);
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (pendingMediaRequest == request) pendingMediaRequest = null;
            }

            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                // 网页问"能不能拿位置"时，先看 Android 运行时权限在不在：
                // 没拿到系统权限就直接 allow，H5 只会收到一个说不清的位置错误。
                if (hasLocationPermission()) {
                    callback.invoke(origin, true, false);
                    return;
                }
                pendingGeoCallback = callback;
                pendingGeoOrigin = origin;
                try {
                    requestPermissions(new String[]{
                            "android.permission.ACCESS_FINE_LOCATION",
                            "android.permission.ACCESS_COARSE_LOCATION"}, GEO_PERM_REQUEST);
                } catch (Exception e) {
                    // 弹不出系统授权（比如 ROM 限制）时要把网页那边结掉，
                    // 不能留着 callback 让 H5 一直卡在"正在请求定位"
                    pendingGeoCallback = null;
                    pendingGeoOrigin = null;
                    callback.invoke(origin, false, false);
                }
            }
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
                if (MainActivity.this.filePathCallback != null) {
                    MainActivity.this.filePathCallback.onReceiveValue(null);
                }
                MainActivity.this.filePathCallback = filePathCallback;

                Intent intent = fileChooserParams.createIntent();
                cameraUri=null;
                try {
                    java.io.File dir=new java.io.File(getCacheDir(),"capture");dir.mkdirs();
                    java.io.File target=java.io.File.createTempFile("photo-",".jpg",dir);
                    cameraUri=androidx.core.content.FileProvider.getUriForFile(MainActivity.this,getPackageName()+".files",target);
                    Intent camera=new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
                    camera.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,cameraUri);
                    camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    intent=Intent.createChooser(intent,"选择照片或拍照").putExtra(Intent.EXTRA_INITIAL_INTENTS,new Intent[]{camera});
                } catch(Exception ignored) {cameraUri=null;}
                try {
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST_CODE);
                } catch (ActivityNotFoundException e) {
                    MainActivity.this.filePathCallback = null;
                    Toast.makeText(MainActivity.this, "未能打开系统相册或相机", Toast.LENGTH_SHORT).show();
                    return false;
                }
                return true;
            }

            // 网页里的 alert/confirm/prompt 不接管的话，系统会弹它自己那套
            // 「网址为 https://appassets.androidplatform.net 的网页显示…」——既把内部地址露给用户，
            // 样式也和应用的卡片脱节。三个回调全部接过来，用自己的对话框呈现。
            // 注意：每条分支都必须把 JsResult 结掉（confirm 或 cancel），否则网页那头的 JS 会一直卡住。
            @Override
            public boolean onJsAlert(WebView view, String url, String message, final android.webkit.JsResult result) {
                if (isFinishing() || isDestroyed()) { result.cancel(); return true; }
                new android.app.AlertDialog.Builder(MainActivity.this)
                        .setTitle("轻塑")
                        .setMessage(message)
                        .setPositiveButton("知道了", (dialog, which) -> result.confirm())
                        .setOnCancelListener(dialog -> result.cancel())
                        .show();
                return true;
            }

            @Override
            public boolean onJsConfirm(WebView view, String url, String message, final android.webkit.JsResult result) {
                if (isFinishing() || isDestroyed()) { result.cancel(); return true; }
                new android.app.AlertDialog.Builder(MainActivity.this)
                        .setTitle("轻塑")
                        .setMessage(message)
                        .setPositiveButton("确定", (dialog, which) -> result.confirm())
                        .setNegativeButton("取消", (dialog, which) -> result.cancel())
                        .setOnCancelListener(dialog -> result.cancel())
                        .show();
                return true;
            }

            @Override
            public boolean onJsPrompt(WebView view, String url, String message, String defaultValue,
                                      final android.webkit.JsPromptResult result) {
                if (isFinishing() || isDestroyed()) { result.cancel(); return true; }
                final float density = getResources().getDisplayMetrics().density;
                final android.widget.EditText input = new android.widget.EditText(MainActivity.this);
                input.setText(defaultValue == null ? "" : defaultValue);
                input.setSelection(input.getText().length());
                input.setSingleLine(false);
                input.setMaxLines(4);
                input.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                        | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
                android.widget.LinearLayout box = new android.widget.LinearLayout(MainActivity.this);
                box.setOrientation(android.widget.LinearLayout.VERTICAL);
                box.setPadding((int) (20 * density), (int) (6 * density), (int) (20 * density), 0);
                box.addView(input, new android.widget.LinearLayout.LayoutParams(
                        android.widget.LinearLayout.LayoutParams.MATCH_PARENT,
                        android.widget.LinearLayout.LayoutParams.WRAP_CONTENT));
                new android.app.AlertDialog.Builder(MainActivity.this)
                        .setTitle("轻塑")
                        .setMessage(message)
                        .setView(box)
                        .setPositiveButton("确定", (dialog, which) -> result.confirm(input.getText().toString()))
                        .setNegativeButton("取消", (dialog, which) -> result.cancel())
                        .setOnCancelListener(dialog -> result.cancel())
                        .show();
                input.requestFocus();
                input.post(() -> {
                    android.view.inputmethod.InputMethodManager imm =
                            (android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                    if (imm != null) imm.showSoftInput(input, 0);
                });
                return true;
            }
        });

        // Load the main web dashboard
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html");

        // Notification permission is requested when the user enables reminders.

        // 启动即在原生层查一次线上版本：页面自己加载失败时更要能提醒更新
        UpdateManager.check(this, false);
        ReminderReceiver.schedule(this);
    }

    // ================= 定位授权：H5 发起，原生决定 =================
    private static final int GEO_PERM_REQUEST = 2026;
    private GeolocationPermissions.Callback pendingGeoCallback;
    private String pendingGeoOrigin;

    // ================= 麦克风授权：私聊语音 =================
    private static final int MIC_PERM_REQUEST = 2028;
    private static final int MIC_PREFLIGHT_REQUEST = 2029;
    private PermissionRequest pendingMediaRequest;
    // 网页取消或退后台后，旧系统弹窗仍可能返回；结果回来前不接下一次授权。
    private boolean micPermissionInFlight;
    private boolean micPreflightInFlight;
    private boolean mediaPermissionStopped;
    private boolean mediaPermissionDestroyed;

    private boolean canGrantMediaPermission() {
        return !mediaPermissionStopped && !mediaPermissionDestroyed && !isFinishing() && !isDestroyed();
    }

    private boolean hasMicrophonePermission() {
        return checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    private static boolean isTrustedAudioRequest(PermissionRequest request) {
        Uri origin = request.getOrigin();
        if (origin == null || !"https".equals(origin.getScheme())
                || !"appassets.androidplatform.net".equals(origin.getHost())
                || origin.getUserInfo() != null || (origin.getPort() != -1 && origin.getPort() != 443)) {
            return false;
        }
        String[] resources = request.getResources();
        // 混合摄像头/DRM 等资源的请求也整条拒绝，不转交系统授权。
        return resources != null && resources.length == 1
                && PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0]);
    }

    private void settleMediaRequest(PermissionRequest request, boolean granted) {
        if (request == null) return;
        try {
            if (granted && canGrantMediaPermission() && isTrustedAudioRequest(request)
                    && hasMicrophonePermission()) {
                request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            } else {
                request.deny();
            }
        } catch (Exception ignored) {
            // WebView 已取消的请求不能再回调。
        }
    }

    private void denyPendingMediaRequest() {
        PermissionRequest request = pendingMediaRequest;
        pendingMediaRequest = null;
        settleMediaRequest(request, false);
    }

    private void handleMediaPermissionRequest(PermissionRequest request) {
        if (request == null) return;
        denyPendingMediaRequest();
        if (!canGrantMediaPermission() || !isTrustedAudioRequest(request) || micPermissionInFlight) {
            settleMediaRequest(request, false);
            return;
        }
        if (hasMicrophonePermission()) {
            settleMediaRequest(request, true);
            return;
        }
        pendingMediaRequest = request;
        micPermissionInFlight = true;
        getSharedPreferences("qingsu", MODE_PRIVATE).edit().putBoolean("mic_requested", true).apply();
        try {
            requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, MIC_PERM_REQUEST);
        } catch (Exception e) {
            micPermissionInFlight = false;
            denyPendingMediaRequest();
            Toast.makeText(this, "系统没让调起录音授权，语音发不了", Toast.LENGTH_LONG).show();
        }
    }

    public String microphonePermissionState() {
        if (hasMicrophonePermission()) return "granted";
        boolean asked = getSharedPreferences("qingsu", MODE_PRIVATE).getBoolean("mic_requested", false);
        if (!asked) return "prompt";
        return shouldShowRequestPermissionRationale(android.Manifest.permission.RECORD_AUDIO) ? "denied" : "blocked";
    }

    public void requestMicPreflight() {
        if (hasMicrophonePermission()) {
            notifyMicPreflight(true);
            return;
        }
        if (micPreflightInFlight) return;
        micPreflightInFlight = true;
        getSharedPreferences("qingsu", MODE_PRIVATE).edit().putBoolean("mic_requested", true).apply();
        try {
            requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, MIC_PREFLIGHT_REQUEST);
        } catch (Exception error) {
            micPreflightInFlight = false;
            notifyMicPreflight(false);
        }
    }

    private void notifyMicPreflight(boolean granted) {
        if (webView == null) return;
        webView.post(() -> {
            if (isFinishing() || isDestroyed()) return;
            try {
                webView.evaluateJavascript(
                        "window.qsMicPermissionResult&&window.qsMicPermissionResult(" + granted + ")", null);
            } catch (Exception ignored) {
                // WebView 已销毁时不再回调网页。
            }
        });
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission("android.permission.ACCESS_COARSE_LOCATION")
                == android.content.pm.PackageManager.PERMISSION_GRANTED
                || checkSelfPermission("android.permission.ACCESS_FINE_LOCATION")
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    private void settleGeoCallback(boolean granted) {
        final GeolocationPermissions.Callback cb = pendingGeoCallback;
        final String origin = pendingGeoOrigin;
        pendingGeoCallback = null;
        pendingGeoOrigin = null;
        if (cb == null || origin == null) return;
        try {
            cb.invoke(origin, granted, false);
        } catch (Exception ignored) {
            // 页面这时可能已经关掉了：回调失败不需要提示，但绝不能抛出去
        }
    }

    // ================= 第五批：开 App 先查通知权限 =================
    private static final int NOTIF_PERM_REQUEST = 2025;
    public void askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            try {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},
                        NOTIF_PERM_REQUEST);
                return;
            } catch (Exception ignored) {
            }
        }
        // Android 12 及以下没有这个运行时弹窗，直接送到位
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName()));
            } else {
                startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())));
            }
        } catch (Exception e) {
            Toast.makeText(this, "打不开系统设置，请在设置里手动找到轻塑", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == MIC_PREFLIGHT_REQUEST) {
            micPreflightInFlight = false;
            notifyMicPreflight(hasMicrophonePermission());
            return;
        }
        if (requestCode == MIC_PERM_REQUEST) {
            if (!micPermissionInFlight) return;
            micPermissionInFlight = false;
            PermissionRequest request = pendingMediaRequest;
            pendingMediaRequest = null;
            if (request == null) return;
            boolean granted = permissions != null && grantResults != null
                    && permissions.length == 1 && grantResults.length == 1
                    && android.Manifest.permission.RECORD_AUDIO.equals(permissions[0])
                    && grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED
                    && hasMicrophonePermission();
            settleMediaRequest(request, granted);
            if (!granted && canGrantMediaPermission()) {
                Toast.makeText(this, "没给麦克风权限，语音发不了；可以在系统设置里打开",
                        Toast.LENGTH_LONG).show();
            }
            return;
        }
        if (requestCode == GEO_PERM_REQUEST) {
            boolean ok = false;
            for (int i = 0; i < grantResults.length; i++) {
                if (grantResults[i] == android.content.pm.PackageManager.PERMISSION_GRANTED) ok = true;
            }
            settleGeoCallback(ok);
            if (!ok) {
                Toast.makeText(this, "没给定位权限，App 里就取不到位置；可以在个人中心手填城市",
                        Toast.LENGTH_LONG).show();
            }
            return;
        }
        if (requestCode != NOTIF_PERM_REQUEST) {
            return;
        }
        boolean granted = grantResults.length > 0 && grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED;
        Toast.makeText(this, granted
                ? "通知已开启，使用应用期间可以接收提醒"
                : "通知还是关着的，提醒只会在应用内出现", Toast.LENGTH_LONG).show();
        if (webView != null) {
            webView.post(new Runnable() {
                @Override
                public void run() {
                    webView.evaluateJavascript("if (window.onAppResume) { window.onAppResume(); }", null);
                }
            });
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        mediaPermissionStopped = false;
    }

    @Override
    protected void onStop() {
        mediaPermissionStopped = true;
        denyPendingMediaRequest();
        super.onStop();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 关键：当用户从系统「通知设置」或「使用情况访问权限」授权后点返回，即时触发前端无刷新更新
        if (webView != null) {
            webView.post(new Runnable() {
                @Override
                public void run() {
                    webView.evaluateJavascript("if (window.onAppResume) { window.onAppResume(); }", null);
                }
            });
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PNG_EXPORT_REQUEST) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null && pendingPng != null) {
                writeExport(data.getData(), pendingPng, "回顾图片已保存", "图片没保存，请重新选择位置");
            }
            pendingPng = null;
            return;
        }
        if(requestCode==SAVE_CSV_REQUEST){
            if(resultCode==RESULT_OK && data!=null && data.getData()!=null && pendingExport!=null){
                writeExport(data.getData(), pendingExport.getBytes(java.nio.charset.StandardCharsets.UTF_8), "记录文件已保存", "文件未保存，请重试");
            }
            pendingExport=null;return;
        }
        if (requestCode == FILE_CHOOSER_REQUEST_CODE) {
            if (filePathCallback != null) {
                Uri[] results = null;
                if (resultCode == Activity.RESULT_OK && data != null) {
                    if (data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    } else if (data.getClipData() != null) {
                        int count = data.getClipData().getItemCount();
                        results = new Uri[count];
                        for (int i = 0; i < count; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    }
                }
                if(resultCode==RESULT_OK && results==null && cameraUri!=null)results=new Uri[]{cameraUri};
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
                cameraUri=null;
            }
        }
    }

    private void writeExport(Uri uri, byte[] bytes, String success, String failure) {
        exportBusy = true;
        final android.content.ContentResolver resolver = getApplicationContext().getContentResolver();
        exports.execute(() -> {
            String message = success;
            try (java.io.OutputStream out = resolver.openOutputStream(uri)) {
                if (out == null) throw new java.io.IOException("No output stream");
                out.write(bytes);
            } catch (Exception error) { message = failure; }
            final String result = message;
            runOnUiThread(() -> {
                exportBusy = false;
                if (!isFinishing() && !isDestroyed()) Toast.makeText(this, result, Toast.LENGTH_LONG).show();
            });
        });
    }

    @Override
    public void onBackPressed() {
        if(webView!=null){webView.evaluateJavascript("(function(){if(window.handleNativeBack)return window.handleNativeBack();return false;})()",value->{if(!"true".equals(value))exitOrNavigate();});return;}
        exitOrNavigate();
    }
    private void exitOrNavigate() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            if (System.currentTimeMillis() - backPressedTime < 2000) {
                super.onBackPressed();
            } else {
                backPressedTime = System.currentTimeMillis();
                Toast.makeText(this, "再按一次退出减脂塑形伴侣", Toast.LENGTH_SHORT).show();
            }
        }
    }

    @Override
    protected void onDestroy() {
        mediaPermissionDestroyed = true;
        denyPendingMediaRequest();
        exports.shutdown();
        if (androidBridge != null) androidBridge.release();
        if(filePathCallback!=null){filePathCallback.onReceiveValue(null);filePathCallback=null;}
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
