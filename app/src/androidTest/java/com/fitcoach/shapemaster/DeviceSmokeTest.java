package com.fitcoach.shapemaster;

import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.Bitmap;
import android.webkit.WebView;
import android.view.ViewGroup;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import java.io.File;
import java.io.FileOutputStream;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Exercises our own release WebView through Android instrumentation, not browser DevTools. */
@RunWith(AndroidJUnit4.class)
public class DeviceSmokeTest {
    private final Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
    private WebView web;
    private String js(String script) throws Exception {
        CountDownLatch latch=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        instrumentation.runOnMainSync(()->web.evaluateJavascript(script,v->{result.set(v);latch.countDown();}));
        assertTrue("JS callback timed out",latch.await(10,TimeUnit.SECONDS));return result.get();
    }
    private void waitFor(String script) throws Exception {
        long end=System.currentTimeMillis()+30000;
        while(System.currentTimeMillis()<end){if("true".equals(js(script)))return;Thread.sleep(200);}
        fail("Condition timed out: "+script);
    }
    private void screenshot(String name) throws Exception {
        Thread.sleep(800); // Wait for the WebView compositor, not just the DOM mutation.
        File dir=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa");dir.mkdirs();
        Bitmap image=instrumentation.getUiAutomation().takeScreenshot();assertNotNull(image);
        try(FileOutputStream out=new FileOutputStream(new File(dir,name+".png"))){image.compress(Bitmap.CompressFormat.PNG,100,out);}
        image.recycle();
    }
    @Test(timeout=240000) public void releaseUserJourney() throws Exception {
        String user="usbqa"+System.currentTimeMillis();String password="UsbQaOnly!123";
        JSONObject body=new JSONObject().put("username",user).put("password",password).put("age",30).put("height",170).put("weight_jin",160).put("target_weight_jin",140);
        HttpsURLConnection request=(HttpsURLConnection)new URL(BuildConfig.API_BASE_URL+"/api/register").openConnection();
        request.setRequestMethod("POST");request.setConnectTimeout(15000);request.setReadTimeout(15000);request.setDoOutput(true);request.setRequestProperty("Content-Type","application/json");
        try(java.io.OutputStream output=request.getOutputStream()){output.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        assertEquals("Fixture registration",200,request.getResponseCode());request.disconnect();
        File fixtureDir=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa");fixtureDir.mkdirs();
        File fixture=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/fixture.txt");
        try(FileOutputStream out=new FileOutputStream(fixture)){out.write(user.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        Intent intent=new Intent(instrumentation.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK);
        instrumentation.getTargetContext().startActivity(intent);
        AtomicReference<MainActivity> resumed=new AtomicReference<>();
        for(int i=0;i<100 && resumed.get()==null;i++){
            instrumentation.runOnMainSync(()->{
                for(android.app.Activity a:androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(androidx.test.runner.lifecycle.Stage.RESUMED))
                    if(a instanceof MainActivity)resumed.set((MainActivity)a);
            });Thread.sleep(100);
        }
        MainActivity activity=resumed.get();assertNotNull("App activity did not resume",activity);
        instrumentation.runOnMainSync(()->activity.setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT));
        instrumentation.runOnMainSync(()->web=(WebView)((ViewGroup)activity.findViewById(android.R.id.content)).getChildAt(0));
        try {
        waitFor("document.readyState==='complete' && typeof submitLogin==='function'");
        js("document.getElementById('login-username').value="+JSONObject.quote(user)+";document.getElementById('login-password').value="+JSONObject.quote(password)+";submitLogin();");
        waitFor("state.dashboardLoaded===true");
        assertEquals("160",js("state.currentWeightJin"));
        assertEquals("true",js("API_BASE.startsWith('https:')"));
        assertEquals("true",js("document.documentElement.scrollWidth<=window.innerWidth+1"));
        screenshot("dashboard");
        StringBuilder layout=new StringBuilder("[");
        final double cssDensity=Double.parseDouble(js("devicePixelRatio"));
        for(int width:new int[]{320,360,390,768,1440}){
            instrumentation.runOnMainSync(()->web.setLayoutParams(new android.widget.FrameLayout.LayoutParams((int)Math.round(width*cssDensity),ViewGroup.LayoutParams.MATCH_PARENT)));
            js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';");Thread.sleep(400);
            if(Math.abs(width-Double.parseDouble(js("innerWidth")))>1){
                String diagnostic=js("JSON.stringify([...document.querySelectorAll('body *')].filter(e=>e.offsetParent&&e.getBoundingClientRect().right>"+width+"&&e.getBoundingClientRect().width>30).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right,scroll:e.scrollWidth,client:e.clientWidth})))");
                File report=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/overflow.json");
                try(FileOutputStream out=new FileOutputStream(report)){out.write(diagnostic.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
                screenshot("narrow-overflow");
            }
            assertEquals("Viewport density="+cssDensity+" native="+web.getWidth(),width,Double.parseDouble(js("innerWidth")),1.0);
            for(String tab:new String[]{"dashboard","recipes","workout","body","takeout","charts","gemini"}){
                js("switchTab('"+tab+"')");Thread.sleep(50);
                assertEquals(width+"/"+tab+" document overflow","true",js("document.documentElement.scrollWidth<=window.innerWidth+1"));
            }
            if(layout.length()>1)layout.append(',');layout.append(js("JSON.stringify({requested:"+width+",width:innerWidth,scroll:document.documentElement.scrollWidth})"));
        }
        layout.append(']');
        File layoutFile=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/layout.json");
        try(FileOutputStream out=new FileOutputStream(layoutFile)){out.write(layout.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        instrumentation.runOnMainSync(()->web.setLayoutParams(new android.widget.FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT)));
        js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';switchTab('dashboard');");Thread.sleep(400);
        js("document.getElementById('input-weight').value='150';document.getElementById('weight-unit').value='jin';saveWeight();");
        waitFor("state.currentWeightJin===150 && state.weightHistory[state.weightHistory.length-1].jin===150");
        js("openRecordManager('weight');");waitFor("!!document.querySelector('dialog[open]')");screenshot("history");js("document.getElementById('account-tools-dialog').close()");
        js("openSharingSettings()");waitFor("!!document.getElementById('share-enabled')");screenshot("share-settings");js("document.getElementById('account-tools-dialog').close()");
        js("openRecordManager('food')");waitFor("!!document.querySelector('dialog[open]')");
        instrumentation.runOnMainSync(activity::onBackPressed);waitFor("!document.querySelector('dialog[open]')");
        for(String tab:new String[]{"dashboard","recipes","workout","body","takeout","charts","gemini"}){
            js("switchTab('"+tab+"')");
            assertEquals(tab+" panel visible","true",js("document.getElementById('panel-"+tab+"').classList.contains('active')"));
            assertEquals(tab+" horizontal overflow","true",js("document.documentElement.scrollWidth<=window.innerWidth+1"));
        }
        js("switchTab('workout');openExerciseDetail(0)");Thread.sleep(500);screenshot("exercise");js("closeExerciseDetail()");
        js("switchTab('gemini');document.getElementById('chat-input').value='我现在多重';sendChatMessage();");
        waitFor("document.getElementById('chat-messages-box').innerText.includes('150')");screenshot("chat");
        js("openReminderSettings()");waitFor("!!document.getElementById('reminder-enabled')");screenshot("reminders");
        js("document.getElementById('account-tools-dialog').close();switchTab('dashboard')");
        // Exercise the real JavaScript -> native loopback transport with a protocol fixture.
        try(java.net.ServerSocket fixtureServer=new java.net.ServerSocket(0,2,java.net.InetAddress.getByName("127.0.0.1"))){
            int port=fixtureServer.getLocalPort();
            Thread fixtureThread=new Thread(()->{
                try(java.net.Socket client=fixtureServer.accept()){
                    java.io.BufferedReader reader=new java.io.BufferedReader(new java.io.InputStreamReader(client.getInputStream()));
                    String line;while((line=reader.readLine())!=null && !line.isEmpty()){}
                    byte[] response="{\"status\":\"ok\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    client.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "+response.length+"\r\nConnection: close\r\n\r\n").getBytes(java.nio.charset.StandardCharsets.US_ASCII));client.getOutputStream().write(response);
                }catch(Exception ignored){}
            });fixtureThread.start();
            js("window.nativeTransportCheck=null;nativeLocalRequest('http://127.0.0.1:"+port+"/health',{},5000).then(r=>window.nativeTransportCheck=r.status).catch(e=>window.nativeTransportCheck=String(e));");
            waitFor("window.nativeTransportCheck===200");fixtureThread.join(3000);
        }
        // Validate document write callback using an app-owned URI; no personal files involved.
        File exportDir=new File(activity.getCacheDir(),"capture");exportDir.mkdirs();File csv=new File(exportDir,"qa-export.csv");
        android.net.Uri uri=androidx.core.content.FileProvider.getUriForFile(activity,activity.getPackageName()+".files",csv);
        java.lang.reflect.Field pending=MainActivity.class.getDeclaredField("pendingExport");pending.setAccessible(true);pending.set(activity,"项目,数值\n测试,123");
        instrumentation.runOnMainSync(()->activity.onActivityResult(1002,android.app.Activity.RESULT_OK,new Intent().setData(uri)));
        assertTrue(csv.isFile());assertTrue(new String(java.nio.file.Files.readAllBytes(csv.toPath()),java.nio.charset.StandardCharsets.UTF_8).contains("测试,123"));csv.delete();
        android.content.SharedPreferences reminder=activity.getSharedPreferences("reminders",0);
        boolean enabled=reminder.getBoolean("enabled",false);int hour=reminder.getInt("hour",20),minute=reminder.getInt("minute",0);
        WebAppInterface bridge=new WebAppInterface(activity,web);assertTrue(bridge.configureReminder(true,23,59));
        assertTrue(new JSONObject(bridge.reminderStatus()).getBoolean("enabled"));
        new ReminderReceiver().onReceive(activity,new Intent(Intent.ACTION_TIMEZONE_CHANGED));
        assertTrue(bridge.configureReminder(enabled,hour,minute));
        String publicUrl=new org.json.JSONArray("["+js("state.publicUrl")+"]").getString(0);
        js("logoutUser()");waitFor("state.token===null");
        // The web visitor page runs in a second WebView with no native bridge or login state.
        instrumentation.runOnMainSync(()->{
            web=new WebView(activity);web.getSettings().setJavaScriptEnabled(true);web.getSettings().setDomStorageEnabled(true);web.getSettings().setAllowFileAccess(false);
            web.setWebViewClient(new android.webkit.WebViewClient());activity.setContentView(web);web.loadUrl(publicUrl);
        });
        waitFor("!!document.getElementById('public-view')");
        assertEquals("true",js("document.getElementById('public-view').innerText.includes('150')"));
        assertEquals("true",js("getComputedStyle(document.getElementById('app-main')).display==='none'"));
        assertEquals("true",js("typeof window.AndroidBridge==='undefined'"));
        screenshot("web-public");
        } finally {
            try {js("localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY);if(typeof logoutUser==='function')logoutUser();");} catch(Exception ignored){}
            instrumentation.runOnMainSync(()->activity.setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED));
        }
    }
}
