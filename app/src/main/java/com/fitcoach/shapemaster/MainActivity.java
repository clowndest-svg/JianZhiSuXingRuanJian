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
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import androidx.webkit.WebViewAssetLoader;
import android.widget.Toast;

public class MainActivity extends Activity {

    private static final int FILE_CHOOSER_REQUEST_CODE = 1001;
    private ValueCallback<Uri[]> filePathCallback;
    private WebView webView;
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
            if (pendingPng != null) return;
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
        webView.addJavascriptInterface(new WebAppInterface(this, webView), "AndroidBridge");

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
        });
        webView.setWebChromeClient(new WebChromeClient() {
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
                try (java.io.OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                    if (out == null) throw new java.io.IOException("No output stream");
                    out.write(pendingPng);
                    Toast.makeText(this, "回顾图片已保存", Toast.LENGTH_LONG).show();
                } catch (Exception e) { Toast.makeText(this, "图片没保存，请重新选择位置", Toast.LENGTH_LONG).show(); }
            }
            pendingPng = null;
            return;
        }
        if(requestCode==SAVE_CSV_REQUEST){
            if(resultCode==RESULT_OK && data!=null && data.getData()!=null && pendingExport!=null){
                try(java.io.OutputStream out=getContentResolver().openOutputStream(data.getData())){
                    if(out==null)throw new java.io.IOException("No output stream");
                    out.write(pendingExport.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    Toast.makeText(this,"记录文件已保存",Toast.LENGTH_LONG).show();
                }catch(Exception e){Toast.makeText(this,"文件未保存，请重试",Toast.LENGTH_LONG).show();}
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
        if(filePathCallback!=null){filePathCallback.onReceiveValue(null);filePathCallback=null;}
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
