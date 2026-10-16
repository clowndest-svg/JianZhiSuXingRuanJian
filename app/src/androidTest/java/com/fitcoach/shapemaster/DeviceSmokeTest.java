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
        // 上一轮的截图不会自己消失（MuMu 的共享存储里 adb rm 都不一定生效），
        // 留着就会把"旧证据"当成"本轮证据"。开跑前先清掉本目录的 png/json。
        File[] stale=fixtureDir.listFiles();
        if(stale!=null)for(File f:stale){String n=f.getName();if(n.endsWith(".png")||n.endsWith(".json"))f.delete();}
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
        final java.util.Set<Integer> distinctWidths=new java.util.TreeSet<>();
        final double cssDensity=Double.parseDouble(js("devicePixelRatio"));
        for(int width:new int[]{320,360,390,768,1440}){
            final int requested=width;
            // 宽度用"改窗口 + device-width"来驱动，别在 meta 里写死 width=N：
            // 实测 Blink 取 max(meta 宽度, 窗口 CSS 宽度)，上一档更宽的窗口会把下一档
            // 顶住（360 档量到 410），窄屏就成了假覆盖。
            instrumentation.runOnMainSync(()->web.setLayoutParams(new android.widget.FrameLayout.LayoutParams((int)Math.round(requested*cssDensity),ViewGroup.LayoutParams.MATCH_PARENT)));
            js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';");Thread.sleep(400);
            double got=Double.parseDouble(js("innerWidth"));
            // 先钉住"这一档真的跑在 requested 宽度上"，否则后面的溢出判据只是在
            // 同一块屏上重复跑，绿了也不代表窄屏没问题。
            assertEquals(width+" 档的 CSS 视口宽度（跑溢出判据之前）",width,got,1.0);
            distinctWidths.add((int)Math.round(got));
            // 溢出诊断只在真的溢出时留档：以前按"请求宽度"过滤，视口被钳时
            // 会把正常贴右缘的元素报成溢出，产物看着有内容其实什么都没发生。
            if(Double.parseDouble(js("document.documentElement.scrollWidth"))>got+1){
                String diagnostic=js("JSON.stringify([...document.querySelectorAll('body *')].filter(e=>e.offsetParent&&e.getBoundingClientRect().right>innerWidth+1&&e.getBoundingClientRect().width>30).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:Math.round(e.getBoundingClientRect().width),right:Math.round(e.getBoundingClientRect().right),scroll:e.scrollWidth,client:e.clientWidth})))");
                File report=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/overflow.json");
                try(FileOutputStream out=new FileOutputStream(report)){out.write(diagnostic.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
                screenshot("narrow-overflow");
            }
            for(String tab:new String[]{"dashboard","recipes","workout","body","takeout","charts","gemini"}){
                js("switchTab('"+tab+"')");Thread.sleep(50);
                assertEquals(width+"/"+tab+" document overflow","true",js("document.documentElement.scrollWidth<=window.innerWidth+1"));
            }
            double settled=Double.parseDouble(js("innerWidth"));
            // 弹回更宽＝这一档的窄屏判据其实没在窄屏上跑。把三种口径一起打出来，
            // 才能分清是 View 被重新量了，还是 WebView 自己钳了布局视口。
            assertEquals(width+" 档切完七个页签后视口没弹回更宽(expected/innerWidth/native/visualViewport/pageScale="
                    +width+"/"+settled+"/"+web.getWidth()+"/"+js("visualViewport?visualViewport.width:-1")
                    +"/"+js("visualViewport?visualViewport.scale:-1")+")",width,settled,1.0);
            if(layout.length()>1)layout.append(',');layout.append(js("JSON.stringify({requested:"+width+",width:innerWidth,scroll:document.documentElement.scrollWidth})"));
        }
        layout.append(']');
        File layoutFile=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/layout.json");
        try(FileOutputStream out=new FileOutputStream(layoutFile)){out.write(layout.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        File vpFile=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/viewport-env.txt");
        // 判据放在留档之后：这一档红的时候，我要能在产物里看到它到底跑成了多宽，
        // 而不是只拿到一个"没生效"的结论。
        // 断点从 CSSOM 现读，不写死数字：样式表加了新断点而这里没跟上时，
        // 覆盖结论必须是红，而不是一直通。
        String condRaw=js("JSON.stringify(Array.from(document.styleSheets).flatMap(s=>{try{return Array.from(s.cssRules)}catch(e){return[]}}).filter(r=>r.conditionText).map(r=>r.conditionText))");
        String conds=new org.json.JSONArray("["+condRaw+"]").getString(0);
        java.util.TreeSet<Integer> breaks=new java.util.TreeSet<>();
        java.util.regex.Matcher bm=java.util.regex.Pattern.compile("max-width:\\s*(\\d+)px").matcher(conds);
        while(bm.find())breaks.add(Integer.parseInt(bm.group(1)));
        assertTrue("从 CSSOM 读不到任何宽度断点，窄屏覆盖无从判断: "+conds, !breaks.isEmpty());
        // 每个断点区间都必须真的有一档落在里面：宽度已按档硬判，这里再漏就是
        // 矩阵选错了档，而不是设备不配合。
        StringBuilder bandGaps=new StringBuilder();
        int prev=0;
        for(int b:breaks){
            boolean hit=false;
            for(int w:distinctWidths) if(w>prev && w<=b) hit=true;
            if(!hit) bandGaps.append("(").append(prev).append(",").append(b).append("]");
            prev=b;
        }
        boolean wideCovered=false;
        for(int w:distinctWidths) if(w>prev) wideCovered=true;
        if(!wideCovered) bandGaps.append("(").append(prev).append(",inf)");
        try(FileOutputStream out=new FileOutputStream(vpFile)){out.write(("density="+cssDensity+" widths="+distinctWidths
                +" breakpoints="+breaks+" gaps="+bandGaps).getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        assertEquals("断点区间没有全覆盖（实测视口="+distinctWidths+" 断点="+breaks+"）: ",0,bandGaps.length());
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
        js("switchTab('workout');openExerciseDetail(0)");Thread.sleep(700);
        // 用户报的 bug：3D 视角工具栏叠在画布上把人体遮住。这里用几何量出来，
        // 不靠"看着好像没挡"。overlap>0 就是真挡住了。
        // getBoundingClientRect 是视口绝对坐标，画布左侧还有页面边距（模拟器上画布
        // 从 x=81 起），占比必须减去 canvas.left，否则量到的是"标签离屏幕左边多远"。
        String geo = js("JSON.stringify((function(){            var c=document.getElementById('ex-detail-canvas').getBoundingClientRect();            var b=document.querySelector('.exd-camera-bar').getBoundingClientRect();            var bs=[].slice.call(document.querySelectorAll('.exd-cam-btn')).map(function(x){return Math.round(x.getBoundingClientRect().top);});            var ov=document.querySelector('.exd-viewport-overlay').getBoundingClientRect();            return {canvasBottom:Math.round(c.bottom),canvasWidth:Math.round(c.width),canvasLeft:Math.round(c.left),ovLeftRel:Math.round(ov.left-c.left),ovRightRel:Math.round(ov.right-c.left),clearanceRight:Math.round(c.right-ov.right),barTop:Math.round(b.top),                overlap:Math.max(0,Math.round(c.bottom-b.top)),                barHeight:Math.round(b.height),rowTops:bs,                overlayRightFrac:+((ov.right-c.left)/c.width).toFixed(2),barWidthFrac:+(b.width/c.width).toFixed(2)};            })())");
        org.json.JSONObject g = new org.json.JSONObject(new org.json.JSONArray("[" + geo + "]").getString(0));
        assertEquals("视角工具栏与画布零重叠（不遮人体）: " + geo, 0, g.getInt("overlap"));
        org.json.JSONArray tops = g.getJSONArray("rowTops");
        int lo = Integer.MAX_VALUE, hi = Integer.MIN_VALUE;
        for (int k = 0; k < tops.length(); k++) { int t = tops.getInt(k); lo = Math.min(lo, t); hi = Math.max(hi, t); }
        assertTrue("四个视角按钮仍在同一行: " + geo, hi - lo <= 2);
        assertTrue("工具栏不宽于画布: " + geo, g.getDouble("barWidthFrac") <= 1.0);
        assertTrue("信息标签紧贴画布左缘: " + geo, g.getInt("ovLeftRel") <= 10);
        assertTrue("信息标签右边界留在画布 2/3 以内（按画布自身坐标算，不含页面左边距）: " + geo,
                g.getDouble("overlayRightFrac") <= 0.66);
        assertTrue("右上角至少留出 48px 给厂商悬浮侧栏: " + geo, g.getInt("clearanceRight") >= 48);
        // 3D 骨骼演示：必须证明"真画出人形、骨骼真的被驱动、而且这一帧在屏幕上
        // 是个能看的人"。coverage>6 只能证明画了东西，裁掉半身、相机顺着体长轴
        // 看过去（压成一团）这两种都能照样绿。selfTest 在同帧内渲染并回读像素。
        String s3d = js("JSON.stringify(window.Body3D ? Body3D.selfTest(            poseFromTable(exActivePoseKey, exActiveArch, 0.3), posePlane(exActivePoseKey), ex3DCamera.yaw)             : {status:'none'})");
        org.json.JSONObject j3d = new org.json.JSONObject(new org.json.JSONArray("[" + s3d + "]").getString(0));
        // evaluateJavascript 回传的是 JSON 编码后的字符串字面量，先过一层 JSONArray 取回原文。
        String st3dRaw = js("JSON.stringify(Body3D.stats())");
        org.json.JSONObject st3d = new org.json.JSONObject(new org.json.JSONArray("[" + st3dRaw + "]").getString(0));
        assertEquals("3D 模型在这台设备上应可用（否则退回画块）: " + s3d, "ready", st3d.getString("status"));
        assertTrue("3D 自测必须真的画出人形: " + s3d, j3d.getBoolean("ok"));
        assertTrue("画面上几乎没有墨迹: " + s3d, j3d.getDouble("coverage") > 3.0);
        assertTrue("人体只占画面一小条，取景没贴住身体: " + s3d, j3d.getDouble("fill") > 45.0);
        assertTrue("有肢体被裁在画面外，取景没包住全身: " + s3d, j3d.getDouble("ndcMax") <= 0.99);
        assertTrue("相机几乎沿体长轴看过去，任何姿势都会压成一团: " + s3d, j3d.getDouble("endOn") <= 0.5);
        assertTrue("骨骼没有被驱动，等于站桩假动画: " + st3d.toString(), st3d.getInt("solvedBones") >= 10);
        assertTrue("取景算出过荒谬相机距离（坏帧会让画面歪掉而不自知）: " + st3d.toString(),
                st3d.isNull("badFrame"));
        assertEquals("有骨骼被算成 NaN 后退回绑定姿态: " + st3d.toString(), 0, st3d.getInt("nanBones"));
        js("setEx3DAngle('front')"); Thread.sleep(600);
        screenshot("exercise-3d-front");
        String sFront = js("JSON.stringify(Body3D.selfTest(            poseFromTable(exActivePoseKey, exActiveArch, 0.3), posePlane(exActivePoseKey), ex3DCamera.yaw))");
        org.json.JSONObject jFront = new org.json.JSONObject(new org.json.JSONArray("[" + sFront + "]").getString(0));
        assertTrue("转到正面视角后仍要画得出人体: " + sFront, jFront.getBoolean("ok"));
        assertTrue("正面视角把肢体裁出了画面: " + sFront, jFront.getDouble("ndcMax") <= 0.99);
        assertTrue("正面视角几乎沿体长轴看: " + sFront, jFront.getDouble("endOn") <= 0.5);
        js("setEx3DAngle('side')"); Thread.sleep(600);
        File b3dFile=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/body3d.json");
        try(FileOutputStream out=new FileOutputStream(b3dFile)){
            out.write(("{\"current\":"+j3d+",\"front\":"+jFront+",\"stats\":"+st3d+"}")
                    .getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        screenshot("exercise-3d-side");
        js("setEx3DAngle('3d')"); Thread.sleep(300);
        // 只测第一个动作＝只测了"躺着的那一个"。整套训练计划里每个动作都要
        // 画得完整（不裁肢体）、不压成一条线，逐个过一遍。
        int exCount = Integer.parseInt(js("window.__currentExercises ? __currentExercises.length : 0"));
        assertTrue("训练计划至少给出 3 个动作供 3D 检查", exCount >= 3);
        StringBuilder exBad = new StringBuilder();
        for (int i = 0; i < exCount; i++) {
            js("openExerciseDetail(" + i + ")"); Thread.sleep(1200);
            String each = js("JSON.stringify(Body3D.selfTest(                poseFromTable(exActivePoseKey, exActiveArch, 0.5), posePlane(exActivePoseKey), ex3DCamera.yaw))");
            org.json.JSONObject e = new org.json.JSONObject(new org.json.JSONArray("[" + each + "]").getString(0));
            String label = js("document.getElementById('ex-detail-name').innerText")
                    .replace("\\u0022", "").replace("\"", "");
            if (!e.optBoolean("ok", false)) exBad.append("[").append(i).append(label)
                    .append(" 没画全 cov=").append(e.optDouble("coverage", -1))
                    .append(" fill=").append(e.optDouble("fill", -1))
                    .append(" ndc=").append(e.optDouble("ndcMax", -1)).append("]");
            else if (e.optDouble("ndcMax", 9) > 0.99) exBad.append("[").append(i).append(label).append(" 肢体被裁 ").append(e.optDouble("ndcMax", 9)).append("]");
            else if (e.optDouble("endOn", 0) > 0.6) exBad.append("[").append(i).append(label).append(" 几乎沿体长轴看 ").append(e.optDouble("endOn", 0)).append("]");
        }
        assertEquals("每个动作的 3D 演示都要画全: " + exBad, "", exBad.toString());
        js("openExerciseDetail(0)"); Thread.sleep(900);
        screenshot("exercise-3d");
        screenshot("exercise");
        js("closeExerciseDetail()");
        js("switchTab('gemini');document.getElementById('chat-input').value='我现在多重';sendChatMessage();");
        waitFor("document.getElementById('chat-messages-box').innerText.includes('150')");screenshot("chat");
        js("openReminderSettings()");waitFor("!!document.getElementById('reminder-enabled')");screenshot("reminders");
        js("document.getElementById('account-tools-dialog').close();switchTab('dashboard')");
        // --- r132: 今日完整日确认（后端早有接口，界面上第一次有入口）---
        assertEquals("完整日确认按钮存在", "true", js("!!document.getElementById('day-complete-btn')"));
        waitFor("!document.getElementById('day-complete-btn').disabled");
        String dayLabel = js("document.getElementById('day-complete-state').innerText");
        assertTrue("确认状态先回读服务端: " + dayLabel, dayLabel.contains("还没确认") || dayLabel.contains("已确认"));
        js("document.getElementById('day-complete-btn').click()");
        waitFor("state.dayComplete && state.dayComplete.confirmed===true");
        assertTrue("确认后界面跟着改口: " + js("document.getElementById('day-complete-state').innerText"),
                js("document.getElementById('day-complete-state').innerText").contains("已确认"));
        assertTrue("确认后按钮变成可撤销: " + js("document.getElementById('day-complete-btn').innerText"),
                js("document.getElementById('day-complete-btn').innerText").contains("取消"));
        js("document.getElementById('day-complete-btn').click()");
        waitFor("state.dayComplete && state.dayComplete.confirmed===false");
        assertEquals("撤销后回到未确认", "true", js("document.getElementById('day-complete-state').innerText.includes('还没确认')"));

        // --- r132: 键盘可达性与读屏可见性 ---
        assertEquals("底导项都是可聚焦的按钮角色", "true", js(
                "[...document.querySelectorAll('.nav-item')].every(e=>e.getAttribute('role')==='button'&&e.getAttribute('tabindex')==='0')"));
        assertEquals("底导字号不低于 11px", "true", js(
                "[...document.querySelectorAll('.nav-item>span:not(.nav-icon)')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=11)"));
        assertEquals("主按钮触控高度不小于 44px", "true", js(
                "[...document.querySelectorAll('.btn-primary')].every(e=>!e.offsetParent||e.getBoundingClientRect().height>=44)"));
        assertEquals("回车能激活 role=button 的餐别切换", "\"dinner\"", js(
                "(function(){const el=document.getElementById('slot-chip-dinner');"
                + "el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));return state.selectedMealSlot;})()"));
        assertEquals("切换后 pressed 跟着走", "true", js(
                "document.getElementById('slot-chip-dinner').getAttribute('aria-pressed')==='true'"
                + "&&document.getElementById('slot-chip-lunch').getAttribute('aria-pressed')==='false'"));
        js("selectMealSlot('lunch')");
        js("switchTab('dashboard')");
        assertEquals("五个弹窗都声明成对话框", "5", js(
                "document.querySelectorAll('.modal-card[role=dialog][aria-modal=true]').length"));
        js("openProfileModal()");
        waitFor("document.getElementById('profile-modal').classList.contains('show')");
        assertEquals("弹窗打开时背景被 inert 屏蔽", "true", js(
                "document.querySelector('.bottom-nav').inert===true"
                + "&&document.getElementById('auth-modal').getAttribute('aria-hidden')==='true'"));
        assertEquals("焦点落在弹窗内部", "true", js(
                "document.getElementById('profile-modal').contains(document.activeElement)"));
        instrumentation.runOnMainSync(activity::onBackPressed);
        waitFor("!document.getElementById('profile-modal').classList.contains('show')");
        assertEquals("关闭后背景恢复可用", "false", js("document.querySelector('.bottom-nav').inert===true"));
        assertEquals("缺口图有文字摘要且不依赖颜色", "true", js(
                "['达标','未达','超支','未记录'].every(w=>document.getElementById('chart-deficit-summary').innerText.includes(w))"
                + "||document.getElementById('chart-deficit-summary').innerText.includes('暂无')"));
        screenshot("day-complete");

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
