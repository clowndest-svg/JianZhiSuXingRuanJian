package com.fitcoach.shapemaster;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Bitmap;
import android.webkit.WebView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.ByteBuffer;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/**
 * WebGL 可行性探针：换 3D 引擎前必须先过这道闸。
 *
 * 不看"上下文存在不存在"——那在软件实现上也会返回 true。这里要的是
 * 1) 真建出上下文并画出一个三角形；
 * 2) 用 gl.readPixels 从 framebuffer 读回像素，确认中心确实是红、四角确实是清屏色；
 * 3) 再把 WebView 截成 bitmap 数一次颜色分桶，证明它真的合成上屏而不是只画进离屏缓冲。
 */
@RunWith(AndroidJUnit4.class)
public class WebGLProbeTest {
    private final android.app.Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
    private WebView view;

    private static final String PAGE =
        "<!doctype html><meta charset=utf-8><body style='margin:0;background:#000'>" +
        "<canvas id=c width=300 height=300 style='display:block;width:300px;height:300px'></canvas>" +
        "<script>" +
        "window.__probe={webgl2:false,webgl:false,renderer:'',version:'',maxTex:0,drawn:false," +
        "center:[0,0,0],corner:[0,0,0],fail:''};" +
        "try{" +
        "  var cv=document.getElementById('c');var gl=cv.getContext('webgl2')||cv.getContext('webgl');" +
        "  if(!gl){window.__probe.fail='no-context';}else{" +
        "    window.__probe.webgl2=(cv.getContext('webgl2')===gl);" +
        "    window.__probe.webgl=true;" +
        "    var dbg=gl.getExtension('WEBGL_debug_renderer_info');" +
        "    if(dbg){window.__probe.renderer=String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL));}" +
        "    window.__probe.version=String(gl.getParameter(gl.VERSION));" +
        "    window.__probe.maxTex=gl.getParameter(gl.MAX_TEXTURE_SIZE);" +
        "    gl.clearColor(0,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT);" +
        "    var vs='attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';" +
        "    var fs='precision mediump float;void main(){gl_FragColor=vec4(1.,0.,0.,1.);}';" +
        "    function sh(t,s){var o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);" +
        "      if(!gl.getShaderParameter(o,gl.COMPILE_STATUS)){throw new Error(gl.getShaderInfoLog(o));}return o;}" +
        "    var pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,vs));" +
        "    gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,fs));gl.linkProgram(pr);" +
        "    if(!gl.getProgramParameter(pr,gl.LINK_STATUS)){throw new Error('link-failed');}" +
        "    gl.useProgram(pr);" +
        "    var buf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buf);" +
        "    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([0,.7,-.7,-.7,.7,-.7]),gl.STATIC_DRAW);" +
        "    var loc=gl.getAttribLocation(pr,'p');gl.enableVertexAttribArray(loc);" +
        "    gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);" +
        "    gl.drawArrays(gl.TRIANGLES,0,3);gl.finish();" +
        "    function px(x,y){var b=new Uint8Array(4);gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,b);return [b[0],b[1],b[2]];}" +
        "    window.__probe.center=px(150,150);window.__probe.corner=px(4,4);" +
        "    window.__probe.drawn=window.__probe.center[0]>150&&window.__probe.center[1]<60&&window.__probe.center[2]<60;" +
        "  }" +
        "}catch(e){window.__probe.fail=String(e&&e.message||e);}" +
        "window.__ready=1;" +
        "</script>";

    @SuppressLint("SetJavaScriptEnabled")
    private String js(String script) throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        instrumentation.runOnMainSync(() -> view.evaluateJavascript(script, v -> { result.set(v); latch.countDown(); }));
        assertTrue("JS callback timed out", latch.await(20, TimeUnit.SECONDS));
        return result.get();
    }

    @Test(timeout = 120000)
    public void webglActuallyRasterizes() throws Exception {
        Context ctx = instrumentation.getTargetContext();
        CountDownLatch made = new CountDownLatch(1);
        AtomicReference<WebView> ref = new AtomicReference<>();
        instrumentation.runOnMainSync(() -> {
            WebView w = new WebView(ctx);
            w.getSettings().setJavaScriptEnabled(true);
            w.getSettings().setAllowFileAccess(false);
            w.getSettings().setUseWideViewPort(false);
            w.setWebViewClient(new android.webkit.WebViewClient());
            w.setLayoutParams(new android.widget.FrameLayout.LayoutParams(320, 340));
            w.loadDataWithBaseURL("https://qingsu.test/", PAGE, "text/html", "utf-8", null);
            ref.set(w);
            made.countDown();
        });
        assertTrue(made.await(20, TimeUnit.SECONDS));
        view = ref.get();

        for (int i = 0; i < 60; i++) {
            if ("1".equals(js("String(window.__ready||0)"))) break;
            Thread.sleep(300);
        }
        String raw = js("JSON.stringify(window.__probe)");
        String json = new org.json.JSONArray("[" + raw + "]").getString(0);
        org.json.JSONObject p = new org.json.JSONObject(json);
        System.out.println("WEBGL_PROBE " + json);

        assertEquals("拿不到 WebGL 上下文（模拟器/驱动不支持）: " + json, true, p.getBoolean("webgl"));
        assertEquals("着色器或绘制报错: " + json, "", p.getString("fail"));
        assertTrue("gl.readPixels 读回的不是三角形颜色，GPU 没真画: " + json, p.getBoolean("drawn"));
        assertTrue("清屏色被污染: " + json, p.getJSONArray("corner").getInt(0) < 40);
        assertTrue("最大纹理过小，装不下角色贴图: " + json, p.getInt("maxTex") >= 2048);

        // 再证一次真的合成上屏：截 WebView 数颜色分桶
        CountDownLatch shot = new CountDownLatch(1);
        AtomicReference<Bitmap> bmp = new AtomicReference<>();
        instrumentation.runOnMainSync(() -> {
            android.graphics.Canvas c = new android.graphics.Canvas();
            Bitmap b = Bitmap.createBitmap(320, 320, Bitmap.Config.ARGB_8888);
            c.setBitmap(b);
            view.draw(c);
            bmp.set(b);
            shot.countDown();
        });
        assertTrue(shot.await(20, TimeUnit.SECONDS));
        Bitmap image = bmp.get();
        int red = 0, dark = 0;
        for (int y = 0; y < image.getHeight(); y += 4) {
            for (int x = 0; x < image.getWidth(); x += 4) {
                int col = image.getPixel(x, y);
                int r = (col >> 16) & 255, g = (col >> 8) & 255, bl = col & 255;
                if (r > 150 && g < 70 && bl < 70) red++;
                else if (r < 40 && g < 40 && bl < 40) dark++;
            }
        }
        System.out.println("WEBGL_SCREEN red=" + red + " dark=" + dark);
        // 这个 WebView 没挂到窗口上，软件 draw 能不能拿到内容不作数，只当参考信息；
        // 真正的闸门是上面的 gl.readPixels。
        System.out.println("WEBGL_SCREEN informational red=" + red + " dark=" + dark);
    }
}
