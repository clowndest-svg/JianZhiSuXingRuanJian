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
    private void waitFor(String script) throws Exception { waitFor(script, 30); }
    /** MuMu 上的 WebView 偶尔整页无响应（evaluateJavascript 根本不回调），
     *  探针本身抖一下不该判产品死；重试到时限，真不满足照样红，并把最后一次探针的失败原因带出来。 */
    private void waitFor(String script, int seconds) throws Exception {
        long end = System.currentTimeMillis() + seconds * 1000L;
        String last = "";
        while (System.currentTimeMillis() < end) {
            try {
                if ("true".equals(js(script))) return;
                last = "";
            } catch (Throwable t) {
                last = String.valueOf(t.getMessage());
                Thread.sleep(1500);
            }
            Thread.sleep(200);
        }
        fail("Condition timed out: " + script + (last.isEmpty() ? "" : " | 最后一次探针: " + last));
    }
    private void screenshot(String name) throws Exception {
        Thread.sleep(800); // Wait for the WebView compositor, not just the DOM mutation.
        File dir=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa");dir.mkdirs();
        Bitmap image=instrumentation.getUiAutomation().takeScreenshot();assertNotNull(image);
        try(FileOutputStream out=new FileOutputStream(new File(dir,name+".png"))){image.compress(Bitmap.CompressFormat.PNG,100,out);}
        image.recycle();
    }
    /** 把量到的数字原样留档：断言只说"过了"，看图的人要能对上号。 */
    private void dumpQa(String name,String text) throws Exception {
        File f=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/"+name);
        f.getParentFile().mkdirs();
        try(FileOutputStream out=new FileOutputStream(f)){out.write(text.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    }
    private MainActivity launchShell() throws Exception {
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
        instrumentation.runOnMainSync(()->web=(WebView)((ViewGroup)activity.findViewById(android.R.id.content)).getChildAt(0));
        waitFor("document.readyState==='complete' && typeof submitLogin==='function'");
        return activity;
    }

    @Test(timeout=240000) public void toolDialogsAreReadableOnDevice() throws Exception {
        // 这三块界面（分享与隐私 / 我的记录与设置 / 历史记录）机主实拍说"排版丑得离谱"。
        // 观感只能靠看图，但"有没有越界、行高是否一致、开关是不是真控件、
        // 屏上有没有印原始枚举"是能量的——先把可量的钉住，再看图。
        String user="uqa"+System.currentTimeMillis();String password="UsbQaOnly!123";
        org.json.JSONObject body=new org.json.JSONObject().put("username",user).put("password",password)
                .put("nickname","小田").put("age",30).put("height",170).put("weight_jin",160).put("target_weight_jin",140);
        java.net.HttpURLConnection request=(java.net.HttpURLConnection)new URL(BuildConfig.API_BASE_URL+"/api/register").openConnection();
        request.setRequestMethod("POST");request.setConnectTimeout(15000);request.setReadTimeout(15000);request.setDoOutput(true);
        request.setRequestProperty("Content-Type","application/json");
        request.setRequestProperty("X-App-Build",String.valueOf(instrumentation.getTargetContext()
                .getPackageManager().getPackageInfo(instrumentation.getTargetContext().getPackageName(),0).versionCode));
        try(java.io.OutputStream out=request.getOutputStream()){out.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        assertEquals("夹具注册",200,request.getResponseCode());request.disconnect();
        launchShell();
        loginAs(user, password);
        // 夹具这条餐食是后面"历史记录"判据的样本：它没记进去的话，
        // 弹窗只会显示"还没有记录"，报出来的却是"印了原始枚举"——先把种子本身验掉。
        js("postApi('/api/food/log',{slot:'早餐',food_name:'测试燕麦粥',cal:180})"
                +".then(r=>{window.__seed='ok:'+JSON.stringify(r).slice(0,140);})"
                +".catch(e=>{window.__seed='err:'+(e&&e.message);});");
        waitFor("!!window.__seed");
        assertEquals("夹具那条餐食没记进去: " + js("window.__seed"), "true",
                js("window.__seed.indexOf('ok:')===0"));
        waitFor("document.getElementById('account-tool-card')!==null");
        try {
            // 品牌位换成图片后，最容易坏的是"图根本没加载出来"和"被拉成椭圆"
            assertEquals("顶栏品牌图没加载成功或比例不对", "true", js(
                    "(()=>{const i=document.querySelector('.app-brand img.brand-icon');"
                    +"if(!i||!i.complete||i.naturalWidth<64)return false;"
                    +"const r=i.getBoundingClientRect();"
                    +"return Math.abs(r.width-r.height)<=1&&r.width>=28&&r.width<=44;})()"));
            // 顶栏度量：机主说"一上一下不好看、用户名那样展示好丑"。
            // 观感靠看图，但"同一行、不换行、圆点是正圆、层级少一层"是量得出来的。
            // 探针本身要能自证：JS 里任何一处取空元素，evaluateJavascript 只会回 null，
            // 报出来像"产品没通过"，其实是探针写坏了。套一层 try 把真因带回来。
            String hd = js("JSON.stringify((function(){try{"
                    +"var chip=document.querySelector('.account-chip');"
                    +"var icon=document.querySelector('.brand-icon');"
                    +"var dot=document.querySelector('.avatar-dot');"
                    +"var name=document.getElementById('header-username-display');"
                    +"var brand=document.querySelector('.app-brand');"
                    +"var prof=document.querySelector('.brand-profile');"
                    +"var hdr=document.querySelector('.app-header');"
                    +"if(!chip||!icon||!dot||!name||!prof||!hdr)return {probeError:'缺元素 chip='+(!!chip)+"
                    +"' icon='+(!!icon)+' dot='+(!!dot)+' name='+(!!name)+' prof='+(!!prof)+' hdr='+(!!hdr)};"
                    +"var cr=chip.getBoundingClientRect(),ir=icon.getBoundingClientRect(),dr=dot.getBoundingClientRect();"
                    +"var extra=Array.prototype.filter.call(document.querySelectorAll('.header-icon-btn'),function(b){"
                    +"return b.id!=='btn-view-toggle'&&b.offsetHeight>0;}).length;"
                    +"return {chipH:Math.round(cr.height),iconH:Math.round(ir.height),"
                    +"topDiff:Math.abs(Math.round((cr.top+cr.height/2)-(ir.top+ir.height/2))),"
                    +"extraIcons:extra,nameText:name.textContent.trim(),"
                    +"dotW:Math.round(dr.width),dotH:Math.round(dr.height),"
                    +"nameH:Math.round(name.getBoundingClientRect().height),"
                    +"nameLines:Math.round(name.getBoundingClientRect().height/parseFloat(getComputedStyle(name).fontSize)/1.4),"
                    +"profLeft:Math.round(prof.getBoundingClientRect().left),"
                    +"titleLeft:Math.round(brand.querySelector('h1').getBoundingClientRect().left),"
                    +"hdrH:Math.round(hdr.getBoundingClientRect().height),"
                    // 顶栏"堆太高"说的是品牌行 + 模式条；桌面那排导航按钮是导航，
                    // 11 个入口换行是设计的一部分，不该算进这个高度里。
                    +"coreH:(function(){var a=document.querySelector('.header-row-1'),"
                    +"b=document.querySelector('.header-mode-bar'),c=document.querySelector('.mode-diff-hint');"
                    +"return Math.round(a.getBoundingClientRect().height+b.getBoundingClientRect().height"
                    +"+(c&&c.offsetHeight?c.offsetHeight+6:0));})(),"
                    +"navRows:(function(){var n=document.getElementById('desktop-top-nav');"
                    +"if(!n||!n.offsetHeight)return 0;var it=n.querySelector('.d-nav-item');"
                    +"return Math.round(n.getBoundingClientRect().height/(it.getBoundingClientRect().height+6));})(),"
                    +"tiers:Array.from(hdr.children).filter(function(c){return c.offsetHeight>0;}).length,"
                    +"toolsRight:Math.round(cr.right),hdrRight:Math.round(hdr.getBoundingClientRect().right),"
                    +"overflow:document.documentElement.scrollWidth>window.innerWidth+1};"
                    +"}catch(e){return {probeError:String(e&&e.message||e)};}})())");
            org.json.JSONObject hj = new org.json.JSONObject(new org.json.JSONArray("[" + hd + "]").getString(0));
            assertFalse("顶栏度量探针自己失败了: " + hd, hj.has("probeError"));
            dumpQa("header-desktop.json", hj.toString());
            assertEquals("顶栏账号入口和品牌图标不在同一行中线上: " + hd, 0, hj.getInt("topDiff"));
            assertTrue("账号入口比品牌图标矮太多，看着像没对齐: " + hd,
                    hj.getInt("chipH") >= hj.getInt("iconH") - 6);
            // 齿轮和档案摘要是同一个入口，窄屏上白占 40px；机主说的"一上一下"就是它俩把顶栏撑成三层
            assertEquals("顶栏还留着第二颗重复的齿轮: " + hd, 0, hj.getInt("extraIcons"));
            assertEquals("账号入口显示的不是昵称: " + hd, "小田", hj.getString("nameText"));
            assertEquals("头像圆点不是正圆: " + hd, hj.getInt("dotW"), hj.getInt("dotH"));
            assertTrue("头像圆点太小: " + hd, hj.getInt("dotW") >= 22);
            assertEquals("昵称被排成多行（该省略号时没省略）: " + hd, 1, hj.getInt("nameLines"));
            // 档案行挂在品牌文字下面（图标在左边），所以对齐参照是标题而不是图标
            assertEquals("档案行没和标题左对齐: " + hd, hj.getInt("titleLeft"), hj.getInt("profLeft"));
            // 工具组最后一个元素（账号入口）该贴着顶栏右内边，右侧不留大块空白
            assertTrue("顶栏右侧留白过大，工具组没贴到边: " + hd,
                    hj.getInt("hdrRight") - hj.getInt("toolsRight") <= 20);
            // 层级数才是一上一下的直接度量：品牌行 + 模式条（提示条有内容时才算第三块）
            assertTrue("顶栏可见块超过 3 个，还在往堆: " + hd, hj.getInt("tiers") <= 3);
            assertTrue("顶栏主体高度异常（没量到内容或堆太多层）: " + hd,
                    hj.getInt("coreH") >= 80 && hj.getInt("coreH") <= 190);
            assertTrue("整个头部（含桌面导航）高得离谱: " + hd,
                    hj.getInt("hdrH") >= 80 && hj.getInt("hdrH") <= 240);
            assertTrue("桌面导航换行超过 3 排，入口太多了: " + hd, hj.getInt("navRows") <= 3);
            assertFalse("顶栏改动引起横向溢出: " + hd, hj.getBoolean("overflow"));
            // 这张要在开任何弹窗之前拍：上一轮把它放在 openDownloadModal 之后，
            // 取回来的图盖着弹窗，等于没有顶栏证据。
            screenshot("header-clean");
            js("openDownloadModal()");
            waitFor("document.querySelector('#download-apk-modal img.brand-mark')!==null");
            assertEquals("下载弹窗的品牌图没加载成功", "true", js(
                    "(()=>{const i=document.querySelector('#download-apk-modal img.brand-mark');"
                    +"return !!i&&i.complete&&i.naturalWidth>=64&&i.getBoundingClientRect().width>=28;})()"));
            screenshot("brand-header");
            js("closeDownloadModal()");
            // 餐食核对弹窗：机主实拍说它"像在敷衍我"——裸标签、裸按钮、和软件不是一套
            js("document.getElementById('input-meal-text').value='番茄鸡蛋肉汤面';logNaturalMeal();");
            waitFor("document.getElementById('meal-confirm-cal')!==null");
            assertEquals("餐食核对弹窗的输入框没挂在表单行上","true",js(
                    "(()=>{const i=document.getElementById('meal-confirm-cal');"
                    +"const row=i.closest('.td-field-row');if(!row)return false;"
                    +"const r=i.getBoundingClientRect(),rr=row.getBoundingClientRect();"
                    +"return r.width>=rr.width-32&&r.height>=40;})()"));
            // 现在有三个按钮（AI 估算 / 先不记 / 确认并保存）：要钉的不变量是"恰好一个主按钮"
            assertEquals("餐食核对弹窗按钮层级不对（应恰好一个实心主按钮）","true",js(
                    "(()=>{const b=[...document.querySelectorAll('#account-tools-dialog .td-actions button')];"
                    +"const solid=b.filter(x=>getComputedStyle(x).backgroundImage.indexOf('linear')>=0);"
                    +"return b.length>=2&&solid.length===1&&b.indexOf(solid[0])===b.length-1;})()"));
            assertEquals("餐食原文在弹窗里不是主角","true",js(
                    "(()=>{const h=document.querySelector('#account-tools-dialog .td-meal-name');"
                    +"return !!h&&parseFloat(getComputedStyle(h).fontWeight)>=700;})()"));
            screenshot("dialog-meal-confirm");
            js("document.getElementById('account-tools-dialog').close()");
            // 闲聊：一句"你好"必须被接住，界面上还要标得出这条是闲聊
            js("switchTab('gemini');document.getElementById('chat-input').value='你好';sendChatMessage();");
            waitFor("document.body.innerText.indexOf('【闲聊】')>=0");
            Thread.sleep(400);
            assertEquals("闲聊回答里带了编造的数字","true",js(
                    "(()=>{const t=document.body.innerText;const at=t.indexOf('【闲聊】');"
                    +"return !/[0-9][0-9.]* *(斤|kcal|千卡|大卡|岁)/.test(t.slice(at,at+160));})()"));
            screenshot("chat-hello");
            js("switchTab('dashboard');");
            assertEquals("设置卡的行排版不对（行等宽、可点、有箭头、不越界、至少七行）","true",js(
                    "(()=>{const rows=[...document.querySelectorAll('#account-tool-card .td-row')];"
                    +"const w=rows.map(r=>Math.round(r.getBoundingClientRect().width));"
                    +"const h=rows.map(r=>Math.round(r.getBoundingClientRect().height));"
                    +"return rows.length>=7&&new Set(w).size===1&&h.every(x=>x>=44)"
                    +"&&document.documentElement.scrollWidth<=innerWidth+1"
                    +"&&rows.every(r=>!!r.querySelector('.td-chevron'));})()"));

            js("openSharingSettings()");
            waitFor("document.getElementById('account-tools-dialog')&&document.getElementById('account-tools-dialog').open");
            Thread.sleep(500);
            assertEquals("分享与隐私弹窗排版不对（六个真开关、行够高、弹窗不越界、主次按钮不同权重）","true",js(
                    "(()=>{const d=document.getElementById('account-tools-dialog');"
                    +"const sw=[...d.querySelectorAll('.td-switch')];"
                    +"const rows=[...d.querySelectorAll('.td-row')];"
                    +"const rect=d.getBoundingClientRect();"
                    +"const btns=[...d.querySelectorAll('.td-actions button')];"
                    +"return sw.length===6&&sw.every(s=>s.type==='checkbox')"
                    +"&&rows.every(r=>r.getBoundingClientRect().height>=44)"
                    +"&&rect.left>=0&&rect.right<=innerWidth&&rect.bottom<=innerHeight+1"
                    +"&&btns.length===2&&new Set(btns.map(b=>getComputedStyle(b).backgroundImage)).size===2;})()"));
            screenshot("dialog-sharing");
            // 机主："本软件所有弹窗全部居中展示不要放左上角"。
            // 根因是全局 `* { margin:0 }` 打掉了 <dialog> 自带的 margin-inline:auto，
            // 所以这里量的是"真的居中了没有"，不是 CSS 里写没写。
            assertEquals("弹窗没居中（左右留白应大致相等且上下都留了空）", "true", js(
                    "(()=>{const d=document.getElementById('account-tools-dialog');"
                    +"const r=d.getBoundingClientRect();"
                    +"const dl=Math.round(r.left),dr=Math.round(innerWidth-r.right);"
                    +"return Math.abs(dl-dr)<=4&&dl>=0&&r.top>=8&&r.bottom<=innerHeight-8;})()"));
            screenshot("dialog-centered");
            js("document.getElementById('account-tools-dialog').close()");

            js("openRecordManager('food')");
            waitFor("document.getElementById('account-tools-dialog')&&document.getElementById('account-tools-dialog').open");
            Thread.sleep(500);
            String text=js("document.getElementById('account-tools-dialog').innerText");
            assertTrue("历史记录里印了原始枚举: "+text,text.contains("按名称粗估")||text.contains("本人填写"));
            assertFalse("历史记录里印了原始枚举",text.contains("legacy_estimate")||text.contains("nutrition_kb"));
            assertEquals("历史记录的分段控件不对（四等分、恰好一个选中、够高）","true",js(
                    "(()=>{const s=document.querySelector('#account-tools-dialog .td-seg');"
                    +"const b=[...s.querySelectorAll('button')];const w=b.map(x=>Math.round(x.getBoundingClientRect().width));"
                    +"return b.length===4&&new Set(w).size===1"
                    +"&&b.filter(x=>x.getAttribute('aria-selected')==='true').length===1"
                    +"&&b.every(x=>x.getBoundingClientRect().height>=44);})()"));
            screenshot("dialog-history");
            js("document.getElementById('account-tools-dialog').close()");

            js("openBackfill()");
            waitFor("document.getElementById('backfill-kind')!==null");
            Thread.sleep(300);
            // 拆成三条分别断言，并把越界的控件数量放进失败消息：
            // 合成一条只报"false"，看不出是数量、越界还是高度不够
            int rows = Integer.parseInt(js("document.querySelectorAll('#account-tools-dialog .td-field-row').length"));
            assertTrue("补录表单的行数不对（" + rows + "，标签应在输入框上方而不是挤在左侧）", rows >= 7);
            assertEquals("补录表单的标签被挤成窄条（label 宽度不该小于控件）","true",js(
                    "Array.from(document.querySelectorAll('#account-tools-dialog .td-field-row')).every(r=>{"
                    +"const l=r.querySelector('.td-field-label').getBoundingClientRect();"
                    +"const i=r.querySelector('input,select').getBoundingClientRect();"
                    +"return l.width>=i.width-1&&l.height<=30;});"));
            int over = Integer.parseInt(js("Array.from(document.querySelectorAll('#account-tools-dialog input,#account-tools-dialog select'))"
                    + ".filter(x=>x.getBoundingClientRect().right>innerWidth+1).length"));
            assertEquals("补录表单有控件超出屏幕右缘", 0, over);
            int shortOn = Integer.parseInt(js("Array.from(document.querySelectorAll('#account-tools-dialog input,#account-tools-dialog select'))"
                    + ".filter(x=>x.getBoundingClientRect().height<40).length"));
            assertEquals("补录表单有控件高度不足 40px", 0, shortOn);
            screenshot("dialog-backfill");
            js("document.getElementById('account-tools-dialog').close()");

            js("openDownloadModal()");
            waitFor("document.getElementById('apk-fresh-line')!==null");
            Thread.sleep(2500);
            String fresh=js("document.getElementById('apk-fresh-line').innerText");
            assertTrue("下载弹窗没写清包与手机版本: "+fresh,fresh.contains("build "));
            String speed=js("document.getElementById('apk-speed-line').innerText");
            assertFalse("下载耗时仍是写死的数",speed.contains("0.3 MB/s")&&speed.contains("330"));
            assertTrue("测速没给出读数也没说未测: "+speed,speed.contains("实测约")||speed.contains("未测"));
            screenshot("download-modal");
            js("closeDownloadModal()");
        } finally {
            js("logoutUser&&logoutUser()");
        }
    }

    /** 强更门的两端都在真机上量：页面自报的号要和安装包一致，遮罩要真盖得住。 */
    @Test(timeout=300000) public void accountCenterLocationAndDietFilterOnDevice() throws Exception {
        // 这一组只问四件事：壳里的定位通道通不通、个人中心在 320 档排不排得开、
        // 忌口设置是不是真的走到了 DOM、邮件通道没配时界面有没有照实说。
        String user="uqa"+System.currentTimeMillis();String password="UsbQaOnly!123";
        org.json.JSONObject body=new org.json.JSONObject().put("username",user).put("password",password)
                .put("nickname","小田").put("age",30).put("height",170).put("weight_jin",160).put("target_weight_jin",140);
        java.net.HttpURLConnection request=(java.net.HttpURLConnection)new URL(BuildConfig.API_BASE_URL+"/api/register").openConnection();
        request.setRequestMethod("POST");request.setConnectTimeout(15000);request.setReadTimeout(15000);request.setDoOutput(true);
        request.setRequestProperty("Content-Type","application/json");
        request.setRequestProperty("X-App-Build",String.valueOf(instrumentation.getTargetContext()
                .getPackageManager().getPackageInfo(instrumentation.getTargetContext().getPackageName(),0).versionCode));
        try(java.io.OutputStream out=request.getOutputStream()){out.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        assertEquals("夹具注册",200,request.getResponseCode());request.disconnect();
        // 先把系统定位权限授掉：不授的话一调用就弹系统授权框，自动化通道点不到它，
        // 测出来的"失败"其实是我们自己没授权。
        try {
            instrumentation.getUiAutomation().grantRuntimePermission(
                    instrumentation.getTargetContext().getPackageName(),
                    "android.permission.ACCESS_FINE_LOCATION");
        } catch (Exception ignored) {
        }
        launchShell();
        loginAs(user, password);
        waitFor("typeof openAccountCenter==='function'");
        assertEquals("App 里 navigator.geolocation 不可用（壳没开定位）","true",js("!!navigator.geolocation"));

        // 回调必须在超时后落地。挂住不返回＝onGeolocationPermissionsShowPrompt
        // 没把 callback 结掉，界面会永远停在"正在请求定位"。
        js("window.__geo='pending';navigator.geolocation.getCurrentPosition("
                +"p=>{window.__geo='ok:'+(Math.round(p.coords.latitude*100)/100)+','+(Math.round(p.coords.longitude*100)/100);},"
                +"e=>{window.__geo='err:'+(e&&e.code);},{timeout:12000,enableHighAccuracy:false});");
        waitFor("window.__geo.indexOf('pending')!==0");
        // evaluateJavascript 回的是 JSON 编码后的字面量，带引号；先剥一层再判前缀，
        // 否则 startsWith("ok:") 永远不成立——真机第一次跑就是这么误报"回调没落地"的。
        String geo = new org.json.JSONArray("[" + js("window.__geo") + "]").getString(0);
        assertTrue("定位回调没落地，页面会一直卡在请求中: " + geo,
                geo.startsWith("ok:") || geo.startsWith("err:"));
        // 模拟器给不给得出 fix 是随机的：走了哪条分支要留在产物里，
        // 不然"这一版城市落库没验到"和"验过但没提"看着一模一样。
        dumpQa("location.txt", geo + "\n");
        if (geo.startsWith("ok:")) {
            // 真坐标直接回传服务端：验的是"设备上的经纬度能真的认出一个城市"，
            // 不是浏览器里的模拟值。坐标取自上一次回调，不写死。
            String ll = geo.substring(3);
            js("postApi('/api/account/location',{lat:" + ll.split(",")[0] + ",lng:"
                    + ll.split(",")[1] + "}).then(r=>{window.__loc=JSON.stringify(r);})"
                    + ".catch(e=>{window.__loc=JSON.stringify({callError:String(e&&e.message||e)});})");
            waitFor("!!window.__loc");
            org.json.JSONObject lo = new org.json.JSONObject(
                    new org.json.JSONArray("[" + js("window.__loc") + "]").getString(0));
            assertTrue("设备坐标没能存进账号: " + lo.toString(), lo.getBoolean("matched"));
            assertTrue("设备坐标认不出城市: " + lo.toString(), lo.getString("city").length() >= 2);
        }

        // 个人中心：手填城市这条兜底路必须真的能存
        js("openAccountCenter()");
        waitFor("!!document.getElementById('city-input')");
        js("document.getElementById('city-input').value='成都';saveCityManual();");
        waitFor("accountData() && accountData().city==='成都'");
        assertEquals("成都该带出当地口味","true",js("(accountData().cuisines||[]).length>0"));

        // 忌口设置要一路走到 DOM：勾了两项之后，列表里必须出现冲突标注，
        // 但条目数不能少——只排顺序、不藏菜。
        js("postApi('/api/account/preferences',{avoid_tags:['no_spicy','no_seafood']})"
                +".then(r=>{window.__pref=JSON.stringify(r);})");
        waitFor("window.__pref && JSON.parse(window.__pref).avoid_tags.length===2");
        js("refreshAccount()");
        waitFor("accountData() && accountData().avoid_tags.length===2");
        String tav = js("JSON.stringify((function(){renderTakeoutAdvisor();"
                +"var box=document.getElementById('takeout-advisor');var r=rankTakeout();"
                +"var nBad=r.filter(function(x){return x.bad.length;}).length;"
                +"return {items:box.querySelectorAll('.tav-item').length,bad:box.querySelectorAll('.tav-bad').length,"
                +"ranked:r.length,nBad:nBad,nClean:Math.min(3,r.length-nBad),"
                +"meta:(box.querySelector('.tav-meta')||{}).textContent||''};})())");
        org.json.JSONObject tv = new org.json.JSONObject(new org.json.JSONArray("[" + tav + "]").getString(0));
        // 界面只列"前三样推荐 + 全部冲突项"，但冲突的一项都不能少——
        // 藏起用户不能吃的菜，比排错顺序更坏：他还以为自己没勾忌口。
        assertEquals("排序结果里少了菜: " + tav, 12, tv.getInt("ranked"));
        assertEquals("冲突项被藏起来了，没全列出来: " + tav,
                tv.getInt("nBad"), tv.getInt("bad"));
        assertEquals("点单卡的条目数对不上（前三推荐 + 全部冲突）: " + tav,
                tv.getInt("nBad") + tv.getInt("nClean"), tv.getInt("items"));
        assertTrue("勾了不吃辣/海鲜，却一项都没标成冲突: " + tav, tv.getInt("bad") > 0);
        assertTrue("点单顺序卡没显示当前城市: " + tav, tv.getString("meta").contains("成都"));

        // 320 档：弹窗里的开关、密码格、按钮都得是正常控件，且不许横向溢出
        final double cssDensity = Double.parseDouble(js("devicePixelRatio"));
        instrumentation.runOnMainSync(() -> web.setLayoutParams(
                new android.widget.FrameLayout.LayoutParams((int) Math.round(320 * cssDensity),
                        ViewGroup.LayoutParams.MATCH_PARENT)));
        js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';");
        Thread.sleep(400);
        js("document.getElementById('account-tools-dialog').close();openAccountCenter()");
        waitFor("!!document.getElementById('city-input')");
        String dlg = js("JSON.stringify((function(){var d=document.getElementById('account-tools-dialog');"
                +"var dr=d.getBoundingClientRect();"
                +"var over=[].slice.call(d.querySelectorAll('*')).filter(function(e){"
                +"return e.getBoundingClientRect().right>dr.right+1;}).map(function(e){return e.tagName+'.'+e.className;});"
                +"return {sw:d.querySelectorAll('.td-switch').length,pw:d.querySelectorAll('input[type=password]').length,"
                +"city:!!document.getElementById('city-input'),over:over,"
                +"scrollW:d.scrollWidth,clientW:d.clientWidth};})())");
        org.json.JSONObject dj = new org.json.JSONObject(new org.json.JSONArray("[" + dlg + "]").getString(0));
        assertEquals("忌口开关应是 7 个真控件: " + dlg, 7, dj.getInt("sw"));
        assertEquals("改密区应有三个密码格: " + dlg, 3, dj.getInt("pw"));
        assertTrue("320 档没有手填城市输入框: " + dlg, dj.getBoolean("city"));
        assertEquals("320 档个人中心横向溢出: " + dlg, 0, dj.getJSONArray("over").length());
        assertTrue("320 档弹窗内容宽超过可视宽: " + dlg, dj.getInt("scrollW") <= dj.getInt("clientW") + 1);
        screenshot("account-center-320");
        // 机主那台 vivo 就是窄屏，顶栏"一上一下"最容易在这里露馅。
        // MuMu 窗口是 1280 起的，应用会带 desktop-view；只压窗口不会自己切回去，
        // 拍出来是"桌面壳 + 窄视口"的混合体，不代表手机。先真切到手机排版再拍。
        js("document.getElementById('account-tools-dialog').close();applyViewMode('mobile')");
        waitFor("document.body.classList.contains('mobile-view')");
        // 机主实拍那张就是 360 CSS 宽：账号入口掉到品牌下面一行，就是"一上一下"。
        // 宽屏那档量不到这件事，必须在窄屏这一档量。
        String nh = js("JSON.stringify((function(){try{"
                +"var chip=document.querySelector('.account-chip');"
                +"var icon=document.querySelector('.brand-icon');"
                +"var prof=document.querySelector('.brand-profile');"
                +"var name=document.getElementById('header-username-display');"
                +"if(!chip||!icon||!prof||!name)return {probeError:'缺元素'};"
                +"var cr=chip.getBoundingClientRect(),ir=icon.getBoundingClientRect();"
                +"return {rowDiff:Math.abs(Math.round((cr.top+cr.height/2)-(ir.top+ir.height/2))),"
                +"chipPct:Math.round(cr.width/innerWidth*100),innerW:Math.round(innerWidth),"
                +"profH:Math.round(prof.getBoundingClientRect().height),"
                +"profText:prof.textContent.trim().length,"
                +"clipped:name.scrollWidth>name.clientWidth,"
                +"overflow:document.documentElement.scrollWidth>window.innerWidth+1};"
                +"}catch(e){return {probeError:String(e&&e.message||e)};}})())");
        org.json.JSONObject nj = new org.json.JSONObject(new org.json.JSONArray("[" + nh + "]").getString(0));
        assertFalse("窄屏顶栏探针自己失败了: " + nh, nj.has("probeError"));
        dumpQa("header-narrow.json", nj.toString());
        assertEquals("320 档账号入口又掉到品牌下面一行（一上一下）: " + nh, 0, nj.getInt("rowDiff"));
        assertTrue("320 档账号入口宽得压掉品牌: " + nh, nj.getInt("chipPct") <= 45);
        assertTrue("320 档档案摘要没排出来: " + nh, nj.getInt("profH") >= 14 && nj.getInt("profText") > 4);
        assertFalse("320 档顶栏改动引起横向溢出: " + nh, nj.getBoolean("overflow"));
        screenshot("header-320");
        final double phoneDensity = Double.parseDouble(js("devicePixelRatio"));
        instrumentation.runOnMainSync(() -> web.setLayoutParams(
                new android.widget.FrameLayout.LayoutParams((int) Math.round(393 * phoneDensity),
                        ViewGroup.LayoutParams.MATCH_PARENT)));
        js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';");
        Thread.sleep(400);
        assertEquals("393 档没真的跑在 393 CSS 宽上", 393.0, Double.parseDouble(js("innerWidth")), 1.0);
        screenshot("header-393");
        instrumentation.runOnMainSync(() -> web.setLayoutParams(
                new android.widget.FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT)));
        js("applyViewMode('desktop')");
        js("document.getElementById('account-tools-dialog').close()");

        // 找回密码：登录页要有入口，且界面说的话必须和服务端通道状态一致
        assertEquals("登录页没有忘记密码入口", "true",
                js("!!document.querySelector('.link-like[onclick=\"openForgotPassword()\"]')"));
        js("openForgotPassword()");
        waitFor("!!document.getElementById('fg-email')");
        js("fetch(API_BASE+'/api/account/recovery-status').then(r=>r.json())"
                +".then(j=>{window.__rs=j.mail;});");
        waitFor("!!window.__rs");
        // 同样要先剥 evaluateJavascript 的 JSON 引号，否则 "down" 永远不等于 down
        String mailState = new org.json.JSONArray("[" + js("window.__rs") + "]").getString(0);
        String shown = js("document.getElementById('fg-status').textContent");
        if ("down".equals(mailState)) {
            assertTrue("邮件通道没配，界面却没说清楚: " + shown, shown.contains("未接入"));
        } else {
            assertFalse("界面在编造通道状态: " + shown, shown.contains("未接入"));
        }
        js("document.getElementById('account-tools-dialog').close()");
        js("postApi('/api/account/password',{old_password:"+ JSONObject.quote(password)
                +",new_password:'UsbQaOnly!456'}).then(r=>{window.__cp=JSON.stringify(r);})");
        waitFor("window.__cp && JSON.parse(window.__cp).revoked_sessions>=0");
        assertEquals("改密文案没说明其他设备要重登: " + js("window.__cp"), "true",
                js("JSON.parse(window.__cp).msg.indexOf('其他设备')>=0"));
        js("switchTab('dashboard')");
    }

    @Test(timeout=150000) public void clientIdentifiesItselfAndBlocksTheScreen() throws Exception {
        launchShell();
        int packaged=instrumentation.getTargetContext().getPackageManager()
                .getPackageInfo(instrumentation.getTargetContext().getPackageName(),0).versionCode;
        assertEquals("页面自报的构建号不是安装包那一版","true",js("String(APP_BUILD)==='"+packaged+"'"));
        // 网关判定要在真 Blink 上量：访客接口要是被当成业务请求，来看大屏的人会被挡在门外
        assertEquals("真引擎上的接口分类不对","true",
                js("isGatedApi('https://x/api/dashboard')===true"
                   +"&&isGatedApi('https://x/api/public/dashboard?k=1')===false"
                   +"&&isGatedApi('https://x/api/cheer')===false"
                   +"&&isGatedApi('https://x/version.json')===false"));
        assertEquals("遮罩不该在正常版本下出现","true",js("!document.body.classList.contains('update-blocked')"));
        js("showUpdateWall({code:'update_required',min_build:"+(packaged+1)+",your_build:"+packaged
           +",latest:{version_code:"+(packaged+1)+",version_name:'9.9.9',apk_url:'https://124.220.54.64/qingsu.apk',size:5322721}})");
        waitFor("!!document.getElementById('update-wall')");
        assertEquals("强更遮罩没盖满整屏","true",js("(()=>{const w=document.getElementById('update-wall');"
                +"return w.offsetHeight>=innerHeight-2&&w.offsetWidth>=innerWidth-2;})()"));
        assertEquals("强更遮罩不是最上层，底下还能点","true",
                js("(()=>{const e=document.elementFromPoint(Math.round(innerWidth/2),Math.round(innerHeight/2));"
                   +"return !!e&&!!e.closest('#update-wall');})()"));
        assertTrue("屏上没写最低可用版本",js("document.getElementById('update-wall').innerText").contains("构建 "+(packaged+1)));
        assertTrue("屏上没写包体积",js("document.getElementById('update-wall').innerText").contains("5.1 MB"));
        screenshot("update-wall");
        js("document.getElementById('update-wall').remove();document.body.classList.remove('update-blocked');");
    }

    @Test(timeout=240000) public void releaseUserJourney() throws Exception {
        String user="usbqa"+System.currentTimeMillis();String password="UsbQaOnly!123";
        JSONObject body=new JSONObject().put("username",user).put("password",password).put("age",30).put("height",170).put("weight_jin",160).put("target_weight_jin",140);
        HttpsURLConnection request=(HttpsURLConnection)new URL(BuildConfig.API_BASE_URL+"/api/register").openConnection();
        request.setRequestMethod("POST");request.setConnectTimeout(15000);request.setReadTimeout(15000);request.setDoOutput(true);request.setRequestProperty("Content-Type","application/json");
        // 抬门之后不带构建号的请求会被 403，夹具自己就是一个"新版客户端"
        request.setRequestProperty("X-App-Build",String.valueOf(instrumentation.getTargetContext()
                .getPackageManager().getPackageInfo(instrumentation.getTargetContext().getPackageName(),0).versionCode));
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
        loginAs(user, password);
        assertEquals("160",js("state.currentWeightJin"));
        assertEquals("true",js("API_BASE.startsWith('https:')"));
        assertEquals("true",js("document.documentElement.scrollWidth<=window.innerWidth+1"));
        screenshot("dashboard");
        StringBuilder layout=new StringBuilder("[");
        final java.util.Set<Integer> distinctWidths=new java.util.TreeSet<>();
        final double cssDensity=Double.parseDouble(js("devicePixelRatio"));
        final String inkProbe = "JSON.stringify((function(){var c=document.getElementById('ex-detail-canvas');var g2=c.getContext('2d');var W=c.width,H=c.height;var d=g2.getImageData(0,0,W,H).data;var minX=W,minY=H,maxX=-1,maxY=-1,ink=0;for(var y=0;y<H;y+=2){for(var x=0;x<W;x+=2){var i=(y*W+x)*4;var dark=(255-d[i])+(255-d[i+1])+(255-d[i+2]);if(dark>150){ink++;if(x<minX)minX=x;if(x>maxX)maxX=x;if(y<minY)minY=y;if(y>maxY)maxY=y;}}}var el=document.getElementById('ex-detail-canvas').getBoundingClientRect();var top=document.elementFromPoint(el.left+el.width*0.5,el.top+el.height*0.5);return {W:W,H:H,ink:ink,minX:minX,minY:minY,maxX:maxX,maxY:maxY,name:document.getElementById('ex-detail-name').innerText,covered:!(top&&top.id==='ex-detail-canvas'),cssW:document.getElementById('ex-detail-canvas').clientWidth,dpr:window.devicePixelRatio||1};})())";
        final StringBuilder narrowLog = new StringBuilder();
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
            // 顶栏那行在 App 里少一颗「下载App」按钮（app.js 把它藏了），网页版窄屏是更挤的一档。
            // 这一档只有 Blink 量能算，而且必须把按钮真的放回去再量——窄屏不换行是我这轮改的。
            js("var b=document.getElementById('btn-header-download');if(b)b.style.display='';");
            Thread.sleep(150);
            assertEquals(width+" 档顶栏带下载按钮仍不横向溢出","true",
                    js("document.documentElement.scrollWidth<=window.innerWidth+1"));
            assertEquals(width+" 档顶栏账号入口和品牌图标还在同一行","true",
                    js("(function(){var c=document.querySelector('.account-chip'),i=document.querySelector('.brand-icon');"
                    +"if(!c||!i)return false;var a=c.getBoundingClientRect(),b=i.getBoundingClientRect();"
                    +"return Math.abs((a.top+a.height/2)-(b.top+b.height/2))<=4;})()"));
            js("var b=document.getElementById('btn-header-download');if(b)b.style.display='none';");
            Thread.sleep(100);
            if (requested == 320 || requested == 360) {
                // 遮挡与裁切在窄屏才暴露：浮层按百分比排布、弹窗卡片被挤到 288 宽时，
                // 宽屏那档看着一切都好。这里真开弹窗、真从画布回读像素。
                js("switchTab('workout');openExerciseDetail(0)");
                Thread.sleep(900);
                String narrow = js(inkProbe);
                org.json.JSONObject nk = new org.json.JSONObject(new org.json.JSONArray("[" + narrow + "]").getString(0));
                assertFalse(requested + " 档画面被别的元素盖住了: " + narrow, nk.getBoolean("covered"));
                assertTrue(requested + " 档画布上几乎没有笔画: " + narrow, nk.getInt("ink") > 150);
                int nW = nk.getInt("W"), nH = nk.getInt("H");
                assertTrue(requested + " 档人形被裁在画布外: " + narrow,
                        nk.getInt("minX") > 0 && nk.getInt("minY") > 0
                                && nk.getInt("maxX") < nW && nk.getInt("maxY") < nH);
                assertTrue(requested + " 档画布位图没按 dpr 建: " + narrow,
                        nW >= (int) Math.round(nk.getDouble("cssW") * nk.getDouble("dpr")) - 2);
                // 320 档另一处真翻车点：控制栏里那颗说明被两颗按钮挤成四个字一列，
                // 一句话排了十几行。要么够宽、要么整句换到按钮下面，二选一都量得出来。
                String ctl = js("JSON.stringify((function(){var n=document.querySelector('.exd-note').getBoundingClientRect();var b=document.getElementById('ex-detail-play').getBoundingClientRect();return {noteW:Math.round(n.width),noteH:Math.round(n.height),below:n.top>=b.bottom-2};})())");
                org.json.JSONObject cn = new org.json.JSONObject(new org.json.JSONArray("[" + ctl + "]").getString(0));
                assertTrue(requested + " 档说明被挤成竖排（宽 " + cn.getInt("noteW") + "）: " + ctl,
                        cn.getBoolean("below") || cn.getInt("noteW") >= 150);
                assertTrue(requested + " 档说明排了 " + cn.getInt("noteH") + "px 高，行数失控: " + ctl,
                        cn.getInt("noteH") <= 90);
                narrowLog.append(requested).append("档 ").append(nk.toString()).append("\n");
                screenshot("stick-" + requested);
                js("closeExerciseDetail()");
                Thread.sleep(200);
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
        try(FileOutputStream out=new FileOutputStream(new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa/stick-narrow.txt"))){out.write(narrowLog.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
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
        // 火柴人演示只问两件事：有没有东西盖在画布上，人形有没有被裁在画面外。
        // 上一版在视口上叠了三处 absolute 浮层，还把 three.js 的机位函数挂在 window 上，
        // 机主的原话是"手机看网页还有各种遮挡动画，真难看"。这里全部用真坐标量出来。
        String geo = js("JSON.stringify((function(){var c=document.getElementById('ex-detail-canvas').getBoundingClientRect();var pts=[[0.5,0.06],[0.5,0.5],[0.12,0.5],[0.88,0.5],[0.5,0.94],[0.25,0.25],[0.75,0.75]];var hit=[];for(var i=0;i<pts.length;i++){var x=c.left+c.width*pts[i][0],y=c.top+c.height*pts[i][1];var el=document.elementFromPoint(x,y);if(!el||el.id!=='ex-detail-canvas')hit.push(pts[i].join(',')+'->'+(el?(el.id||el.className||el.tagName):'null'));}var strip=document.querySelector('.exd-strip').getBoundingClientRect();var ctl=document.querySelector('.exd-ctl').getBoundingClientRect();return {w:Math.round(c.width),h:Math.round(c.height),hits:hit,stripGap:Math.round(strip.top-c.bottom),ctlGap:Math.round(ctl.top-c.bottom),dpr:window.devicePixelRatio||1,body3d:typeof window.Body3D,cam:typeof window.setEx3DAngle,reset:typeof window.resetEx3DAngle};})())");
        org.json.JSONObject g = new org.json.JSONObject(new org.json.JSONArray("[" + geo + "]").getString(0));
        assertEquals("画布上任何一点都不许被别的元素盖住: " + geo, 0, g.getJSONArray("hits").length());
        assertTrue("信息条挤进了画布区域: " + geo, g.getInt("stripGap") >= 0);
        assertTrue("控制栏挤进了画布区域: " + geo, g.getInt("ctlGap") >= 0);
        assertTrue("画布宽度没跟着视口走: " + geo, g.getInt("w") >= 240);
        assertEquals("3D 层已下线，页面不该再有 Body3D", "undefined", g.getString("body3d"));
        assertEquals("3D 层已下线，不该再有视角切换函数", "undefined", g.getString("cam"));
        assertEquals("3D 层已下线，不该再有机位重置函数", "undefined", g.getString("reset"));
        // 墨迹回读：直接从这块 2D 画布取像素，量出笔画的外接框。
        // 只断言"画了东西"不够——上一版人形被裁掉一半时画面照样有墨。
        // 所以判据是"笔画一个像素都不能贴到画布边缘"，加"人形至少占住一条边的 45%"。
        String inkRaw = js(inkProbe);
        org.json.JSONObject ink = new org.json.JSONObject(new org.json.JSONArray("[" + inkRaw + "]").getString(0));
        assertTrue("画布上几乎没有笔画，动画没画出来: " + inkRaw, ink.getInt("ink") > 150);
        assertTrue("画布位图没按 dpr 建，手机上看是糊的: " + inkRaw,
                ink.getInt("W") >= (int) Math.round(g.getInt("w") * g.getDouble("dpr")) - 2);
        final double edge = 0.02;
        assertTrue("人形贴到画布边缘，肢体被裁: " + inkRaw,
                ink.getInt("minX") > (int) (ink.getInt("W") * edge)
                        && ink.getInt("maxX") < (int) (ink.getInt("W") * (1 - edge))
                        && ink.getInt("minY") > (int) (ink.getInt("H") * edge)
                        && ink.getInt("maxY") < (int) (ink.getInt("H") * (1 - edge)));
        assertTrue("人形只占画面一小条，取景没包住身体: " + inkRaw,
                Math.max((ink.getDouble("maxX") - ink.getInt("minX")) / ink.getInt("W"),
                        (ink.getDouble("maxY") - ink.getInt("minY")) / ink.getInt("H")) > 0.45);
        try (FileOutputStream out = new FileOutputStream(
                new File(instrumentation.getTargetContext().getExternalFilesDir(null), "qa/stick-figure.json"))) {
            out.write(("{\"geo\":" + g + ",\"ink\":" + ink + "}").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        // 只测第一个动作等于只测了"躺着的那一个"。整套计划逐个过：
        // 有没有被盖住、有没有画全、站姿与躺姿的轮廓是不是都还在画面里。
        int exCount = Integer.parseInt(js("window.__currentExercises ? __currentExercises.length : 0"));
        assertTrue("训练计划至少给出 3 个动作供火柴人检查", exCount >= 3);
        StringBuilder exBad = new StringBuilder();
        String standingShot = null;
        for (int i = 0; i < exCount; i++) {
            js("openExerciseDetail(" + i + ")");
            Thread.sleep(900);
            String each = js(inkProbe);
            org.json.JSONObject e = new org.json.JSONObject(new org.json.JSONArray("[" + each + "]").getString(0));
            String label = e.getString("name");
            int W = e.getInt("W"), H = e.getInt("H");
            if (e.getBoolean("covered")) exBad.append("[").append(i).append(label).append(" 画面被盖住]");
            if (e.getInt("ink") < 150) exBad.append("[").append(i).append(label).append(" 没画出笔画]");
            else if (e.getInt("minX") <= (int) (W * edge) || e.getInt("maxX") >= (int) (W * (1 - edge))
                    || e.getInt("minY") <= (int) (H * edge) || e.getInt("maxY") >= (int) (H * (1 - edge)))
                exBad.append("[").append(i).append(label).append(" 肢体被裁 x=").append(e.getInt("minX"))
                        .append("..").append(e.getInt("maxX")).append("/").append(W)
                        .append(" y=").append(e.getInt("minY")).append("..").append(e.getInt("maxY"))
                        .append("/").append(H).append("]");
            else if (Math.max((e.getDouble("maxX") - e.getInt("minX")) / W,
                    (e.getDouble("maxY") - e.getInt("minY")) / H) <= 0.45)
                exBad.append("[").append(i).append(label).append(" 人形只占一小条]");
            // 站姿和躺姿是两套完全不同的轮廓，只在站着做的动作里才暴露比例问题
            if (standingShot == null && "true".equals(js("posePlane(exActivePoseKey)===\"frontal\""))) {
                standingShot = "exstick-standing";
            }
            screenshot("exstick-" + i);
        }
        assertEquals("每个动作的火柴人都要画全、不被盖住: " + exBad, "", exBad.toString());
        assertNotNull("这一版训练计划里没有站着做的动作，站姿外观没被截图覆盖", standingShot);
        js("openExerciseDetail(0)");
        Thread.sleep(900);
        screenshot("exercise-stick");
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
        // 底导原来是 <div role="button" tabindex="0>，换成原生 <button> 之后
        // 焦点与回车激活由浏览器负责，判据要跟着换成新契约，不能继续验那套手搓 ARIA
        assertEquals("底导项都是原生 button（不再用 div 假按钮）", "5", js(
                "[...document.querySelectorAll('.nav-item')].filter(e=>e.tagName==='BUTTON').length"));
        assertEquals("底导项都可聚焦可回车", "true", js(
                "[...document.querySelectorAll('.nav-item')].every(e=>e.tabIndex>=0)"));
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

    /** 探针也要能自证：JS 里任何一处取空元素，evaluateJavascript 只回裸 null，
     *  报出来像"产品没通过"，其实是我们自己把探针写坏了。 */
    private String probeStr(String expr) throws Exception {
        // 不要再套一层 JSON.stringify：evaluateJavascript 已经把返回值编码过一次，
        // 套两层就要剥两层，剥一层拿到的是带引号的 "false"，看着像断言失败。
        String raw = js("(function(){try{return String((" + expr + "));}"
                + "catch(e){return 'probeError:'+(e&&e.message||e);}})()");
        String v = new org.json.JSONArray("[" + raw + "]").getString(0);
        assertFalse("探针跑挂了 " + expr + " -> " + v, v.startsWith("probeError:"));
        return v;
    }

    private org.json.JSONObject probeObj(String expr) throws Exception {
        String raw = js("JSON.stringify((function(){try{return (" + expr + ");}"
                + "catch(e){return {probeError:String(e&&e.message||e)};}})())");
        org.json.JSONObject out = new org.json.JSONObject(new org.json.JSONArray("[" + raw + "]").getString(0));
        assertFalse("探针跑挂了 " + expr + " -> " + raw, out.has("probeError"));
        return out;
    }

    private org.json.JSONObject registerFixture(String user, String nickname, String password) throws Exception {
        org.json.JSONObject body = new org.json.JSONObject().put("username", user).put("password", password)
                .put("nickname", nickname).put("age", 30).put("height", 170)
                .put("weight_jin", 160).put("target_weight_jin", 140);
        java.net.HttpURLConnection request = (java.net.HttpURLConnection)
                new URL(BuildConfig.API_BASE_URL + "/api/register").openConnection();
        request.setRequestMethod("POST");
        request.setConnectTimeout(15000);
        request.setReadTimeout(15000);
        request.setDoOutput(true);
        request.setRequestProperty("Content-Type", "application/json");
        request.setRequestProperty("X-App-Build", String.valueOf(instrumentation.getTargetContext().getPackageManager()
                .getPackageInfo(instrumentation.getTargetContext().getPackageName(), 0).versionCode));
        try (java.io.OutputStream out = request.getOutputStream()) {
            out.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        assertEquals("夹具注册 " + user, 200, request.getResponseCode());
        java.io.InputStream src = request.getInputStream();
        java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int got;
        while ((got = src.read(chunk)) > 0) { buf.write(chunk, 0, got); }
        String text = new String(buf.toByteArray(), "UTF-8");
        request.disconnect();
        return new org.json.JSONObject(text);
    }

    private void waitSessionStable(String why) throws Exception {
        // 页面加载时会自己恢复上一次存的账号，那是第一次 saveAuthSession；手动登录是第二次。
        // 两次之间任何在途请求都会被"账号已切换"这道守卫判成旧请求丢掉——所以必须等号停住，
        // 而不是假定它一定在 2.5 秒内停：慢网络下停得晚，快网络下压根没有恢复。
        String prev = js("sessionGeneration");
        for (int i = 0; i < 8; i++) {
            Thread.sleep(1500);
            String now = js("sessionGeneration");
            if (now.equals(prev)) return;
            prev = now;
        }
        fail(why + "：会话号在 12 秒里一直变，最后两次是 " + prev + " / " + js("sessionGeneration"));
    }

    private void loginAs(String user, String password) throws Exception {
        js("logoutUser&&logoutUser()");
        waitFor("state.token===null", 30);
        waitSessionStable("登出之后会话号还没停");
        js("document.getElementById('login-username').value=" + JSONObject.quote(user)
                + ";document.getElementById('login-password').value=" + JSONObject.quote(password)
                + ";submitLogin();");
        waitFor("state.dashboardLoaded===true && !!state.user", 60);
        waitSessionStable("登录之后会话号还在变（自动恢复和手动登录撞上了），后续请求会被判成旧请求");
    }

    /** 社区、私信、反馈在真机 WebView 里跑一条主线：发帖 → 点赞 → 评论 → 找人 →
     *  发私信 → 杀进程重进看消息还在不在 → 投反馈。跨账号的互动（别人点赞/评论/关注
     *  带来的通知与计数）由 tests/test_integration.py 与外部 Chrome 端到端覆盖：
     *  MuMu 上同一个 WebView 里连续切换账号时，整个网络栈会挂死（连 GET 都不返回），
     *  定位不到本次改动，写在这里免得下一个人重新踩。 */
    @Test(timeout=420000) public void communityChatAndFeedbackOnDevice() throws Exception {
        long base = System.currentTimeMillis();
        String userA = "uqa" + base, userB = "uqa" + (base + 1);
        String password = "UsbQaOnly!123";
        registerFixture(userA, "小田", password);
        String peerPid = registerFixture(userB, "阿毛", password).getString("public_id");
        launchShell();
        loginAs(userA, password);

        js("switchTab('community')");
        waitFor("cm.loaded===true");
        int before = Integer.parseInt(js("document.querySelectorAll('.cm-card').length"));
        assertEquals("列表读完了就不该还挂着 loading", "false", probeStr("String(cm.loading)"));
        if (before == 0) {
            assertEquals("广场空的时候要给一句人话，不是 0 条或空白", "true", js(
                    "document.getElementById('cm-feed-state').textContent.indexOf('广场还空着')>=0"));
        }

        js("expandComposer()");
        waitFor("!document.getElementById('cm-compose-open').hidden");
        String postText = "今天午餐：鸡胸肉150g，糙米饭一碗 #" + base;
        js("document.getElementById('cm-post-text').value=" + JSONObject.quote(postText) + ";syncComposerCount();");
        // evaluateJavascript 回的是 JSON 编码后的字面量，字符串带引号，要先剥一层
        assertEquals("字数计数没跟着输入走", postText.length() + " / 1000",
                probeStr("document.getElementById('cm-post-count').textContent"));
        js("submitPost()");
        waitFor("cm.items.length>" + before);
        String mine = probeStr("(function(){var t=" + JSONObject.quote(postText) + ";"
                + "var c=[].slice.call(document.querySelectorAll('.cm-card')).filter(function(x){"
                + "return x.querySelector('.cm-body').textContent.indexOf(t)>=0;});"
                + "return c.length?c[0].getAttribute('data-post'):'';})()");
        assertTrue("我发的那条没出现在广场: " + mine, mine.matches("\\d+"));
        String myCard = "document.getElementById('post-" + mine + "')";
        assertEquals("正文没显示出来", "true", js(
                myCard + ".querySelector('.cm-body').textContent.indexOf('鸡胸肉')>=0"));
        assertEquals("属地为空时必须写未知，不许留空或编一个省", "true", js(
                "(()=>{const s=" + myCard + ".querySelector('.cm-sub').textContent;"
                + "return s.indexOf('属地 未知')>=0||/属地 (?!未知)[^ ]{1,8} ·/.test(s);})()"));
        assertEquals("我这条的点赞初始值是接口给的 0", "0", probeStr(
                myCard + ".querySelector('[data-like]').textContent"));
        screenshot("community-feed");

        // 点赞与评论：真点击，计数与列表都要跟着动
        js(myCard + ".querySelector('.cm-act').click()");
        waitFor(myCard + ".querySelector('[data-like]').textContent==='1'");
        assertEquals("点赞之后 aria-pressed 没跟上", "true", js(
                myCard + ".querySelector('.cm-act').getAttribute('aria-pressed')==='true'"));
        js(myCard + ".querySelectorAll('.cm-act')[1].click()");
        // 帖子详情现在是整页：正文在 #pl-body，评论输入框固定在底部 #pl-foot
        waitFor("qsPageOpen()===true && !!document.getElementById('cm-comment-text')");
        assertEquals("详情页没显示这条帖子的正文", "true", js(
                "document.getElementById('pl-body').textContent.indexOf("
                + JSONObject.quote(postText) + ")>=0"));
        String commentText = "自己记一句：练后吃的 " + base;
        js("document.getElementById('cm-comment-text').value=" + JSONObject.quote(commentText)
                + ";submitComment(" + mine + ");");
        waitFor("document.getElementById('pl-body').textContent.indexOf("
                + JSONObject.quote(commentText) + ")>=0");
        assertEquals("评论数要跟着涨", "1", probeStr(
                myCard + ".querySelectorAll('.cm-act b')[1].textContent"));
        screenshot("post-detail");
        js("qsCloseAllPages()");
        waitFor("qsPageOpen()===false");

        // 搜索：按昵称找人 → 点进主页 → 从主页发私信，全程真点击
        // 按这一轮那位的轻塑号精确找：昵称"阿毛"在库里已经有一堆历史夹具，
        // 按昵称点开的可能是上一轮那个还没属地的账号，测出来的东西对不上号。
        js("document.getElementById('cm-search-input').value=" + JSONObject.quote(peerPid) + ";searchMembers();");
        waitFor("document.getElementById('cm-search-results').textContent.indexOf("
                + JSONObject.quote(peerPid) + ")>=0");
        assertEquals("搜索结果里要带轻塑号", "true", js(
                "document.getElementById('cm-search-results').textContent.indexOf('轻塑号')>=0"));
        js("document.querySelector('#cm-search-results .cm-row').click()");
        // 机主："用户主页直接跳转页面不要弹窗了，加一个返回按钮"——所以这里查的是页面层不是 dialog
        waitFor("qsPageOpen()===true && document.querySelector('.pl-title').textContent.indexOf("
                + JSONObject.quote("阿毛") + ")>=0");
        assertEquals("整页层没有返回按钮", "true", js(
                "!!document.querySelector('.pl-back') && typeof closePage==='function'"));
        assertEquals("别人的主页不该写成自己", "true", js(
                "document.getElementById('pl-body').textContent.indexOf('这是你自己')<0"));
        assertEquals("主页上的复制按钮要带着真实轻塑号（值放 data-copy，不拼进 onclick）", "true",
                probeStr("(function(){var b=document.querySelector('#pl-body .me-copy');"
                        + "if(!b)return false;"
                        + "var v=b.getAttribute('data-copy')||'';"
                        + "return String(v.length===8 && parseInt(v,10)>0);})()"));
        screenshot("member-home");
        js("[].slice.call(document.querySelectorAll('#pl-slot .td-mini, #pl-body .td-btn'))"
                + ".filter(function(b){return b.textContent.indexOf('私信')>=0;})[0].click()");
        waitFor("qsPageOpen()===true && !!document.getElementById('thread-bubbles')");
        waitFor("cm.wsState==='connected'||cm.wsRetry>4");
        assertEquals("WebSocket 没连上（nginx 的 Upgrade 透传或票据有问题）", "connected", probeStr("cm.wsState"));
        assertEquals("实时连接状态要在界面上看得见", "true", js(
                "document.getElementById('cm-ws-state').textContent.indexOf('已连上')>=0"));
        String dmText = "那条帖子能借我抄一下菜单吗 " + base;
        js("document.getElementById('dm-input').value=" + JSONObject.quote(dmText) + ";sendDM();");
        waitFor("document.getElementById('thread-bubbles').textContent.indexOf("
                + JSONObject.quote(dmText) + ")>=0");
        // 机主："我发消息了上面列表那展示的还是我上一条消息，要刷新才会展示"
        waitFor("cm.convs.length>0 && String(cm.convs[0].last_body).indexOf("
                + JSONObject.quote(dmText) + ")>=0");
        assertEquals("发出去之后会话摘要没立刻跟上", "true", js(
                "String(cm.convs[0].last_body).indexOf(" + JSONObject.quote(dmText) + ")>=0"));
        assertEquals("气泡要能右键/长按出菜单", "true", js(
                "[].slice.call(document.querySelectorAll('.cm-bubble')).length>0"
                + "&&[].slice.call(document.querySelectorAll('.cm-bubble'))"
                + ".every(function(b){return b.getAttribute('oncontextmenu')!==null;})"));
        screenshot("dm-thread");
        // 撤回：走真实端点，撤完气泡改口、正文不再显示
        String recallId = probeStr("(function(){var a=document.querySelectorAll('.cm-bubble.me');"
                + "return a.length?String(a[a.length-1].getAttribute('data-mid')):'0';})()");
        if (!"0".equals(recallId)) {
            js("recallDM(" + recallId + ")");
            waitFor("document.getElementById('thread-bubbles').textContent.indexOf('你撤回了一条消息')>=0");
            assertEquals("撤回之后原话还印在屏上", "false", js(
                    "document.getElementById('thread-bubbles').textContent.indexOf("
                    + JSONObject.quote(dmText) + ")>=0"));
            screenshot("dm-recalled");
        }
        // 撤回会把会话摘要改成"已撤回"，所以"消息是存下来的"这件事要用一条没被撤的来验
        String keepText = "这条不撤，留着验它是存下来的 " + base;
        js("document.getElementById('dm-input').value=" + JSONObject.quote(keepText) + ";sendDM();");
        waitFor("document.getElementById('thread-bubbles').textContent.indexOf("
                + JSONObject.quote(keepText) + ")>=0");
        // 返回要一级一级退：私信是从主页点进去的，所以第一下回到主页，第二下才收起整层
        js("document.querySelector('.pl-back').click()");
        waitFor("qsPageOpen()===true && document.querySelector('.pl-title').textContent.indexOf("
                + JSONObject.quote("阿毛") + ")>=0");
        assertEquals("第一下返回应该退回主页，不该把整层收掉", "true", js(
                "!document.getElementById('page-layer').hidden"));
        js("document.querySelector('.pl-back').click()");
        waitFor("qsPageOpen()===false");
        assertEquals("返回按钮没把页面层收掉", "true", js("document.getElementById('page-layer').hidden"));

        // 同城页签 + 统计可点：都是这轮新加的入口，点了必须有反应
        js("setCommunityTab('city')");
        waitFor("cm.feed==='city'");
        js("switchTab('me')");
        waitFor("document.querySelectorAll('#me-stats .me-stat').length===4");
        assertEquals("统计格必须是能点的按钮", "true", js(
                "document.querySelector('#me-stats .me-stat').tagName==='BUTTON'"));
        js("document.querySelectorAll('#me-stats .me-stat')[2].click()");
        waitFor("qsPageOpen()===true");
        assertEquals("关注列表页没打开", "true", js(
                "document.getElementById('pl-title').textContent.indexOf('关注')>=0"));
        screenshot("stats-following");
        js("qsCloseAllPages()");

        // 杀掉重进：消息必须在，说明它是存下来的而不是内存里的。
        // 先退出再重进：留着本机会话的话，自动恢复会和这次登录抢 sessionGeneration。
        js("logoutUser&&logoutUser()");
        launchShell();
        loginAs(userA, password);
        js("switchTab('messages')");
        long listUntil = System.currentTimeMillis() + 40000;
        String listDiag = "";
        while (System.currentTimeMillis() < listUntil) {
            try {
                listDiag = probeStr("(function(){var a=document.querySelector('.view-panel.active');"
                        + "return 'active='+(a?a.id:'-')+' tab='+cm.msgTab+' convs='+(cm.convs||[]).length"
                        + "+' rows='+document.querySelectorAll('#msg-list .cm-row').length"
                        + "+' state='+(document.getElementById('msg-state')||{}).textContent"
                        + "+' thread='+(cm.thread?1:0)+' token='+(state.token?1:0);})()");
                if (listDiag.contains("rows=0")) { Thread.sleep(1500); continue; }
                break;
            } catch (Throwable t) { listDiag = "探针: " + t.getMessage(); Thread.sleep(1500); }
        }
        assertTrue("重进之后私信列表是空的。现场: " + listDiag, !listDiag.contains("rows=0"));
        assertEquals("重进之后私信列表里找不到那条", "true", js(
                "document.querySelector('#msg-list').textContent.indexOf(" + JSONObject.quote(keepText) + ")>=0"));
        // 这条私信是 A 发出去的，未读在 B 那边：A 自己的角标不该亮。
        // （B 侧的未读计数由 tests/test_integration.py 逐条钉住）
        assertEquals("A 自己发出去的不该算成自己的未读", "true", js(
                "document.getElementById('nav-msg-badge').hidden===true"));
        String peerId = probeStr("(function(){var c=document.querySelector('#msg-list .cm-row');"
                + "var m=(c&&c.getAttribute('onclick')||'').match(/[0-9]+/);return m?m[0]:'';})()");
        assertTrue("会话行上取不到对方 id: " + peerId, peerId.matches("\\d+"));
        js("openThread(" + peerId + ")");
        // 验的是"消息存在服务端"：用那条没被撤回的（原来那条已经撤了，正文本来就不该再出现）
        waitFor("document.getElementById('thread-bubbles').textContent.indexOf("
                + JSONObject.quote(keepText) + ")>=0");
        assertEquals("撤回的那条重进之后又把正文显示出来了", "false", js(
                "document.getElementById('thread-bubbles').textContent.indexOf("
                + JSONObject.quote(dmText) + ")>=0"));
        assertEquals("打开会话之后未读要清零", "0", probeStr(
                "(cm.stats&&Number(cm.stats.dm_unread))===0?'0':'no'"));
        dumpQa("ws-state.txt", probeStr("cm.wsState"));
        screenshot("dm-after-restart");

        // 我的主页：轻塑号、统计、我的帖子
        js("switchTab('me')");
        waitFor("document.getElementById('me-public-id').textContent.trim().length>=8");
        assertEquals("主页要显示 8 位轻塑号", "true", js(
                "/^\\d{8}$/.test(document.getElementById('me-public-id').textContent.trim())"));
        String seenStats = probeStr("(function(){var a=document.querySelectorAll('#me-stats .me-stat b');"
                + "var out=[];for(var i=0;i<a.length;i++)out.push(a[i].textContent);return out.join('/')+"
                + "'|api='+(cm.stats?JSON.stringify(cm.stats):'null');})()");
        assertEquals("获赞要读回来（自己点的那一次）。现场: " + seenStats, "true", js(
                "Number(document.querySelectorAll('#me-stats .me-stat b')[3].textContent)>=1"));
        // 属地：屏上那句必须和接口给的一致（不写死"湖南"，那是环境相关；一致才是要钉的东西）
        assertEquals("主页的属地与接口给的对不上", "true", js(
                "(function(){var r=(cm.stats&&cm.stats.region)||'';"
                + "var t=document.getElementById('me-region').textContent;"
                + "return r? t.indexOf(r)>=0 : t.indexOf('属地未知')>=0;})()"));
        assertEquals("我的帖子列表要含我这条", "true", js(
                "document.getElementById('me-posts').textContent.indexOf('鸡胸肉')>=0"));
        dumpQa("me-stats.json", probeObj("({stats:cm.stats,badge:document.getElementById('nav-msg-badge').textContent,"
                + "pid:document.getElementById('me-public-id').textContent,"
                + "region:document.getElementById('me-region').textContent})").toString());
        screenshot("me-home");

        // 意见反馈：投出去要回编号，列表里要看得见
        js("setFeedbackKind('bug');document.getElementById('fb-text').value="
                + JSONObject.quote("真机自检：计数与角标核对 " + base) + ";syncFeedbackCounters();submitFeedback();");
        waitFor("document.getElementById('fb-result').textContent.indexOf('编号')>=0");
        assertEquals("反馈没给编号", "true", js(
                "/#\\d+/.test(document.getElementById('fb-result').textContent)"));
        js("openMyFeedback()");
        waitFor("document.querySelector('.td-items').textContent.indexOf('真机自检')>=0");
        js("document.getElementById('account-tools-dialog').close()");
        js("switchTab('tools')");
        waitFor("document.getElementById('panel-tools').classList.contains('active')");
        assertEquals("更多页六个工具都要有入口", "6", js(
                "(function(){var want=['recipes','workout','body','takeout','charts','gemini'];"
                + "var have=[].map.call(document.querySelectorAll('#panel-tools .td-row[data-tab]'),"
                + "function(b){return b.getAttribute('data-tab');});"
                + "return want.filter(function(t){return have.indexOf(t)>=0;}).length;})()"));
        assertEquals("工具吸顶条六个入口都在", "6", js(
                "document.querySelectorAll('#tool-strip .ts-chip[data-tab]').length"));
        screenshot("tools-page");

        // 窄屏：四个新页面都要排得开，底部五格都要点得着
        final double density = Double.parseDouble(js("devicePixelRatio"));
        for (int width : new int[]{320, 393}) {
            final int requested = width;
            instrumentation.runOnMainSync(() -> web.setLayoutParams(
                    new android.widget.FrameLayout.LayoutParams((int) Math.round(requested * density),
                            ViewGroup.LayoutParams.MATCH_PARENT)));
            js("document.querySelector('meta[name=viewport]').content='width=device-width, initial-scale=1';");
            Thread.sleep(400);
            js("applyViewMode('mobile')");
            assertEquals(width + " 档没真的跑在该宽度上", (double) width,
                    Double.parseDouble(js("innerWidth")), 1.0);
            for (String tab : new String[]{"community", "messages", "me", "tools", "dashboard"}) {
                js("switchTab('" + tab + "')");
                Thread.sleep(150);
                assertEquals(width + "/" + tab + " 横向溢出", "true", js(
                        "document.documentElement.scrollWidth<=window.innerWidth+1"));
            }
            assertEquals(width + " 档底部导航仍是五格", "5",
                    js("document.querySelectorAll('.bottom-nav .nav-item').length"));
            assertEquals(width + " 档每个底部入口都够点（≥40 宽、≥44 高）", "true", js(
                    "[...document.querySelectorAll('.bottom-nav .nav-item')]"
                    +".every(n=>{const r=n.getBoundingClientRect();return r.width>=40&&r.height>=44;})"));
            assertEquals(width + " 档底部导航文字没被挤到两行", "true", js(
                    "[...document.querySelectorAll('.bottom-nav .nav-item')]"
                    +".every(n=>n.getBoundingClientRect().height<76)"));
            if (requested == 320) {
                js("switchTab('community')");
                Thread.sleep(250);
                screenshot("community-320");
                js("switchTab('me')");
                Thread.sleep(250);
                screenshot("me-320");
            }
        }
        instrumentation.runOnMainSync(() -> web.setLayoutParams(
                new android.widget.FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT)));
        js("applyViewMode('desktop')");
    }
}
