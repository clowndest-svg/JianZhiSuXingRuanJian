/* Original bubble wardrobe. No remote art, paid unlocks, or user content in decorations. */
(function () {
    'use strict';
    const items = [
        {id:'skin-ai',name:'霓虹 AI 娘',type:'AI娘',motif:'ai',shape:'circuit',motion:true,note:'全息耳机 · 心跳微光'},
        {id:'skin-luna',name:'月眠 AI 娘',type:'AI娘',motif:'luna',shape:'arch',motion:true,note:'珍珠月冠 · 星屑轻浮'},
        {id:'skin-sakura',name:'樱花来信',type:'浪漫',motif:'sakura',shape:'petal',motion:true,note:'花瓣信笺 · 春日粉金'},
        {id:'skin-cyber',name:'赛博终端',type:'科幻',motif:'robot',shape:'bevel',motion:true,note:'机甲切角 · 霓虹电路'},
        {id:'skin-cat',name:'薄荷猫耳',type:'萌趣',motif:'cat',shape:'ears',motion:false,note:'软萌猫耳 · 肉垫角标'},
        {id:'skin-bear',name:'焦糖布丁熊',type:'萌趣',motif:'bear',shape:'honey',motion:false,note:'奶油圆耳 · 焦糖淋边'},
        {id:'skin-aurora',name:'极光星轨',type:'科幻',motif:'star',shape:'capsule',motion:true,note:'流光双轨 · 极光渐层'},
        {id:'skin-orbit',name:'失重星球',type:'科幻',motif:'planet',shape:'orbit',motion:true,note:'土星光环 · 失重舷窗'},
        {id:'skin-holo',name:'全息机甲',type:'科幻',motif:'crystal',shape:'panel',motion:false,note:'棱镜装甲 · 冰蓝铭牌'},
        {id:'skin-pixel',name:'像素冒险',type:'动漫',motif:'game',shape:'pixel',motion:false,note:'像素阶梯 · 复古掌机'},
        {id:'skin-manga',name:'热血分镜',type:'动漫',motif:'bolt',shape:'comic',motion:false,note:'漫画墨线 · 速度爆点'},
        {id:'skin-ghost',name:'幽灵夜游',type:'动漫',motif:'ghost',shape:'ghost',motion:true,note:'小幽灵 · 波浪裙摆'},
        {id:'skin-rose',name:'玫瑰情书',type:'浪漫',motif:'rose',shape:'envelope',motion:false,note:'复古信封 · 玫瑰封蜡'},
        {id:'skin-heart',name:'心动频道',type:'浪漫',motif:'heart',shape:'ribbon',motion:true,note:'蝴蝶结 · 温柔心跳'},
        {id:'skin-moon',name:'月光约定',type:'浪漫',motif:'moon',shape:'moon',motion:false,note:'金色弯月 · 星芒花边'},
        {id:'skin-cloud',name:'云朵棉花糖',type:'萌趣',motif:'cloud',shape:'cloud',motion:false,note:'云团轮廓 · 糖果彩虹'},
        {id:'skin-ocean',name:'海盐水母',type:'自然',motif:'jelly',shape:'wave',motion:true,note:'透明海浪 · 漂浮水母'},
        {id:'skin-forest',name:'森野精灵',type:'自然',motif:'leaf',shape:'leaf',motion:false,note:'叶尖边框 · 萤火微光'},
        {id:'skin-tea',name:'抹茶午后',type:'自然',motif:'tea',shape:'cup',motion:false,note:'手帐纸纹 · 抹茶茶盏'},
        {id:'skin-whale',name:'银河鲸落',type:'梦幻',motif:'whale',shape:'whale',motion:true,note:'星海鲸鱼 · 银河弧线'}
    ];
    const frames = {
        circuit:'M18 2H272L298 21V80L280 98H18L2 82V20Z',
        arch:'M3 30Q3 3 38 3H260Q297 3 297 30V77Q297 97 271 97H25Q3 97 3 77Z',
        petal:'M24 4Q8-1 8 17Q-2 20 4 37V66Q-1 83 12 84Q12 101 30 96H267Q286 102 288 85Q303 83 296 65V35Q303 18 288 17Q286-2 268 4Z',
        bevel:'M22 3H276L297 24V76L276 97H24L3 76V24Z',
        ears:'M20 8H40L52 1L64 8H234L247 1L260 8H280Q297 8 297 27V77Q297 96 278 96H22Q3 96 3 77V27Q3 8 20 8Z',
        honey:'M40 3H264Q298 3 298 36V65Q298 97 264 97H40Q2 97 2 65V36Q2 3 40 3Z',
        capsule:'M48 3H252C310 3 310 97 252 97H48C-10 97-10 3 48 3Z',
        orbit:'M64 3H237Q297 3 297 48Q297 97 237 97H64Q3 97 3 48Q3 3 64 3Z',
        panel:'M4 3H273L297 25V97H26L4 76Z',
        pixel:'M12 3H288V12H297V88H288V97H12V88H3V12H12Z',
        comic:'M9 10L280 3L297 17L290 82L298 94L202 91L15 97L3 73Z',
        ghost:'M29 3H270Q297 3 297 29V86Q284 109 270 89Q255 109 240 89Q225 109 210 89Q195 109 180 89Q165 109 150 89Q135 109 120 89Q105 109 90 89Q75 109 60 89Q45 109 30 89Q15 109 3 86V29Q3 3 29 3Z',
        envelope:'M12 3H288Q297 3 297 14V86Q297 97 286 97H14Q3 97 3 86V14Q3 3 12 3Z',
        ribbon:'M23 3H276Q297 3 297 25V75Q297 97 276 97H23L3 83L12 50L3 17Z',
        moon:'M41 3H270Q297 3 297 26V71Q297 97 263 97H31Q3 97 3 72V33Q3 3 41 3Z',
        cloud:'M30 11Q39-1 57 8Q72-1 88 8H213Q229-1 246 8Q265-1 274 14Q302 10 296 37V67Q303 88 282 89Q278 102 258 94H43Q22 102 19 89Q-2 87 4 66V37Q-3 13 30 11Z',
        wave:'M27 3H272Q297 3 297 28V83Q262 103 225 89Q187 76 150 91Q113 105 76 91Q39 77 3 92V28Q3 3 27 3Z',
        leaf:'M43 3H282Q297 3 297 21V64Q297 97 254 97H20Q3 97 3 80V39Q3 3 43 3Z',
        cup:'M10 3H275Q297 3 297 29V61Q297 97 260 97H37Q3 97 3 61V10Q3 3 10 3Z',
        whale:'M28 3H249Q282 3 297 31V69Q282 97 249 97H28Q3 97 3 72V28Q3 3 28 3Z'
    };
    const star = '<path d="m40 5 9 22 24 2-19 16 6 24-20-13-21 13 7-24L7 29l24-2Z" fill="#ffe6a3" stroke="#d89b4f" stroke-width="2.5"/><path d="m32 28 7-13" stroke="#fff" stroke-width="4" stroke-linecap="round"/>';
    const heart = '<path d="M40 69 12 42C-7 22 18 2 40 24 63 2 88 22 68 43Z" fill="#ff82b3" stroke="#b84577" stroke-width="3"/><path d="M17 30q4-13 14-5" stroke="#fff4fa" stroke-width="5" stroke-linecap="round"/>';
    const icons = {
        star,
        heart,
        ai:star,luna:star,
        cat:'<path d="m12 29 2-23 21 13h12L67 6l2 25q10 42-29 42Q1 73 12 29Z" fill="#e7fff3" stroke="#348b78" stroke-width="3"/><path d="m19 13 3 17 10-7m27-10-3 17-10-7" fill="#ffb7ca"/><ellipse cx="26" cy="44" rx="3" ry="5" fill="#234b4e"/><ellipse cx="54" cy="44" rx="3" ry="5" fill="#234b4e"/><path d="m36 51 4 3 4-3m-4 3q-7 10-11 2m11-2q7 10 11 2" stroke="#805d72" stroke-width="2" fill="none"/><path d="m9 49 12 2m38 0 12-2" stroke="#ffb3b9" stroke-width="5"/>',
        bear:'<circle cx="19" cy="20" r="14" fill="#bc7748"/><circle cx="61" cy="20" r="14" fill="#bc7748"/><circle cx="19" cy="20" r="7" fill="#f8c18c"/><circle cx="61" cy="20" r="7" fill="#f8c18c"/><path d="M9 40Q9 12 40 14q31-2 31 26v16Q68 77 40 76 12 77 9 56Z" fill="#f9cb8b" stroke="#9d653e" stroke-width="3"/><ellipse cx="40" cy="56" rx="17" ry="13" fill="#fff0ca"/><circle cx="27" cy="42" r="3" fill="#5c4039"/><circle cx="53" cy="42" r="3" fill="#5c4039"/><path d="m35 52 5 4 5-4m-5 4v5" stroke="#794b3f" stroke-width="3" fill="none"/><path d="M26 16q14-7 28 0" stroke="#d7924d" stroke-width="5"/>',
        sakura:'<path d="M9 73 67 18M24 59l-9-19m29-2 20 9" stroke="#97735b" stroke-width="4" stroke-linecap="round"/><g fill="#ffc9dc" stroke="#d889aa" stroke-width="1.5"><path d="M38 28C12 32 12 14 29 17 14-1 39-8 40 12 56-9 75 8 56 18 80 18 75 41 55 30 58 52 34 51 38 28Z"/><circle cx="20" cy="48" r="9"/><circle cx="61" cy="51" r="7"/></g><circle cx="44" cy="22" r="6" fill="#ffe4a0"/><path d="m42 20 5 4" stroke="#bf8c58" stroke-width="2"/>',
        rose:'<path d="m39 44-3 31m1-11Q10 70 10 53q18-1 27 11m1-8q27 5 28-13-18-1-28 13" fill="#6daf83" stroke="#4c7f62" stroke-width="2"/><path d="M40 55C3 52 4 13 27 12 46-11 77 12 72 33 76 50 59 61 40 55Z" fill="#ed7599" stroke="#b4406b" stroke-width="3"/><path d="M20 21q13-4 26 15M59 15Q42 18 33 38m-15-5q22 22 40 7M30 19q32-2 20 18-20 9-20-11" fill="none" stroke="#ffd2df" stroke-width="3"/>',
        moon:'<path d="M62 8C12 1-1 61 40 73q24 8 35-16C29 75 18 26 62 8Z" fill="#ffdda0" stroke="#b78c4a" stroke-width="3"/><path d="m22 22-5 10m2 21 7 11" stroke="#fff7d7" stroke-width="4" stroke-linecap="round"/><path d="m61 18 4 9 10 1-8 6 2 10-8-5-8 5 2-10-8-6 10-1Z" fill="#fff1bb" stroke="#cfad6c" stroke-width="1.5"/>',
        planet:'<circle cx="40" cy="40" r="26" fill="#a69dea" stroke="#6f65af" stroke-width="3"/><path d="m19 29 41 14M16 41l40 13" stroke="#d7d2ff" stroke-width="7"/><ellipse cx="40" cy="42" rx="38" ry="11" transform="rotate(-25 40 42)" stroke="#e6bd6f" stroke-width="6"/><path d="m16 57 14-5" stroke="#fff0b6" stroke-width="4" stroke-linecap="round"/>',
        robot:'<path d="M38 8v8m-8-9h17" stroke="#70e8ff" stroke-width="3"/><rect x="9" y="17" width="62" height="50" rx="14" fill="#213d64" stroke="#75edff" stroke-width="3"/><rect x="16" y="28" width="48" height="23" rx="8" fill="#0e203b"/><path d="M24 39h9m14 0h9" stroke="#95fff4" stroke-width="5" stroke-linecap="round"/><path d="M31 58h18m-45-25v18m72-18v18" stroke="#ed8eff" stroke-width="4" stroke-linecap="round"/>',
        crystal:'<path d="m40 4 29 22-8 40-21 12L16 63 9 25Z" fill="#bdefff" stroke="#4a9ebd" stroke-width="3"/><path d="M40 4 29 30l11 48 11-48Z" fill="#eefaff"/><path d="m9 25 20 5 22 0 18-4M16 63l13-33m22 0 10 36" stroke="#77b8da" stroke-width="2"/><path d="m40 4 11 26H29Z" fill="#dcceff"/>',
        game:'<path d="M14 9h52v62H14Z" fill="#c9b9e7" stroke="#594a79" stroke-width="3"/><path d="M22 17h36v26H22Z" fill="#e9f7bd" stroke="#796d91" stroke-width="3"/><path d="m31 21 9 14 9-14" fill="#80b788"/><path d="M28 49v15m-7-8h15" stroke="#67587e" stroke-width="5"/><circle cx="54" cy="53" r="4" fill="#fb91b3"/><circle cx="47" cy="62" r="4" fill="#e4ba70"/>',
        bolt:'<path d="M38 2 10 44h25l-7 34L72 29H46L58 2Z" fill="#ffe172" stroke="#322c40" stroke-width="4"/><path d="m10 14 10 8m47 36 10 7M4 62l15-3" stroke="#ef7590" stroke-width="5"/>',
        ghost:'<path d="M10 42C10-5 70-5 70 42v32L58 65 47 75 36 65 24 75 10 67Z" fill="#faf5ff" stroke="#9685cb" stroke-width="3"/><ellipse cx="28" cy="37" rx="4" ry="7" fill="#7861a4"/><ellipse cx="52" cy="37" rx="4" ry="7" fill="#7861a4"/><path d="M34 49q6 9 12 0" stroke="#aa79a8" stroke-width="3"/><path d="m15 47 9 1m32 0 9-1" stroke="#f4b6cf" stroke-width="5"/>',
        cloud:'<path d="M10 45C0 20 25 13 36 25 46 1 77 16 69 39 89 48 71 70 53 61H21C6 66-2 51 10 45Z" fill="#fff" stroke="#9fbed4" stroke-width="3"/><path d="M17 43q24-29 46 0" stroke="#ffb6c8" stroke-width="6"/><path d="M21 45q20-23 38 0" stroke="#ffe4a1" stroke-width="5"/><path d="M27 47q12-13 25 0" stroke="#a6e4d2" stroke-width="5"/>',
        jelly:'<path d="M24 48q-10 20 0 27m13-28q12 14 0 29m13-29q-10 18 2 27m12-29q12 16 0 24" stroke="#c19adb" stroke-width="4" stroke-linecap="round"/><path d="M7 44C5 3 75 1 73 44q-8 10-17 1-8 10-16 0-8 10-16 0-8 10-17-1Z" fill="#c0eeff" stroke="#78b6cf" stroke-width="3"/><path d="M20 28q5-12 17-13" stroke="#fff" stroke-width="6" stroke-linecap="round"/><circle cx="29" cy="35" r="3" fill="#527d99"/><circle cx="51" cy="35" r="3" fill="#527d99"/>',
        leaf:'<path d="M17 70C-8 34 13 5 64 5 79 44 55 73 17 70Z" fill="#a4d2a0" stroke="#568865" stroke-width="3"/><path d="M10 77 59 16m-30 37-6-22m17 9 17-2" stroke="#e9f9d9" stroke-width="4" stroke-linecap="round"/><circle cx="58" cy="64" r="7" fill="#ffe4a5"/><circle cx="72" cy="47" r="3" fill="#fff0be"/>',
        tea:'<path d="M61 31h10q15 23-11 22" stroke="#b78b64" stroke-width="6"/><path d="M12 27h50v24q-2 20-25 20-23 0-25-20Z" fill="#f5efcf" stroke="#a68a64" stroke-width="3"/><ellipse cx="37" cy="28" rx="25" ry="9" fill="#a9bc78" stroke="#8f9f63" stroke-width="2"/><path d="M30 7q-9 8 0 13m16-17q-9 8 0 16" stroke="#b1bea2" stroke-width="3" stroke-linecap="round"/><path d="M5 73h64" stroke="#a68a64" stroke-width="4" stroke-linecap="round"/>',
        whale:'<path d="M7 45q1-34 32-31 29 1 25 31 8 3 11-10 6 19-11 25-45 24-57-15Z" fill="#c1c8f6" stroke="#7e83bd" stroke-width="3"/><path d="M11 48q24 19 51 2-3 17-27 16-19-2-24-18Z" fill="#f5efff"/><circle cx="28" cy="40" r="3" fill="#625c98"/><path d="M43 54q8 10 13-1M31 8q-7-13-13-2m14 3q4-14 13-8" stroke="#a4bdf0" stroke-width="3" stroke-linecap="round"/>'
    };
    const svg = body => '<svg viewBox="0 0 80 80" focusable="false" aria-hidden="true">'+body+'</svg>';
    const get = id => items.find(t=>t.id===id);
    function decor(id) {
        const t=get(id);if(!t)return '';
        const art=t.motif==='ai'||t.motif==='luna'
            ? ''
            : svg(icons[t.motif]);
        const path=frames[t.shape];
        return '<svg class="skin-frame" viewBox="0 0 300 100" preserveAspectRatio="none" focusable="false" aria-hidden="true"><path d="'+path+'"/><path class="skin-stitch" d="'+path+'"/></svg>'
            +'<span class="skin-art skin-art-main'+(t.motif==='ai'||t.motif==='luna'?' skin-portrait':'')+'" aria-hidden="true">'+art+'</span>'
            +'<span class="skin-art skin-art-small" aria-hidden="true">'+svg(t.type==='浪漫'?heart:star)+'</span>';
    }
    function preview(id,large) {
        return '<div class="skin-stage'+(large?' skin-stage-large':'')+'"><div class="skin-sample" data-skin="'+id+'">'+decor(id)
            +'<span class="skin-sample-text">'+(large?'把今天的小确幸，分享给你。':'今天也要开心呀')+'</span>'
            +(large?'<span class="skin-sample-meta">17:20 · 已读</span>':'')+'</div></div>';
    }
    let selected=items[0].id,category='全部',motion=true;
    try{motion=localStorage.getItem('QINGSU_BUBBLE_MOTION')!=='off';}catch(e){}
    function syncMotion(){document.documentElement.dataset.bubbleMotion=(!motion||document.hidden)?'off':'on';}
    document.addEventListener('visibilitychange',syncMotion);
    function gridHTML() {
        return items.filter(t=>category==='全部'||t.type===category).map(t=>'<button type="button" class="skin-card" data-pick-skin="'+t.id+'" aria-pressed="'+(selected===t.id)+'" aria-label="预览'+t.name+'">'
            +preview(t.id,false)+'<span class="skin-card-name">'+t.name+'</span><span class="skin-card-kind">'+t.type+(t.motion?' · 动态':' · 静态')+'</span><span class="skin-check" aria-hidden="true">✓</span></button>').join('');
    }
    function refresh(dialog) {
        dialog.querySelector('.skin-grid').innerHTML=gridHTML();
        const t=get(selected);dialog.querySelector('.skin-live').innerHTML=preview(selected,true);
        dialog.querySelector('.skin-selected-name').textContent=t.name;
        dialog.querySelector('.skin-selected-note').textContent=t.note;
        dialog.querySelectorAll('[data-skin-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.skinCategory===category)));
    }
    function open() {
        selected=get(cm.myTheme)?cm.myTheme:items[0].id;category='全部';syncMotion();
        const types=['全部','AI娘','动漫','科幻','浪漫','萌趣','自然','梦幻'];
        toolDialog('气泡装扮','<section class="bubble-wardrobe"><p class="skin-intro">20 款原创装扮 · 免费切换</p><p class="skin-scope">只装扮你看到的自己消息，对方显示不变。</p>'
            +'<div class="skin-live" aria-hidden="true"></div><div class="skin-selection"><div><strong class="skin-selected-name"></strong><p class="skin-selected-note"></p></div>'
            +'<label class="skin-motion"><input type="checkbox" data-skin-motion'+(motion?' checked':'')+'> 动效</label></div>'
            +'<nav class="skin-categories" aria-label="气泡风格">'+types.map(c=>'<button type="button" data-skin-category="'+c+'" aria-pressed="'+(c==='全部')+'">'+c+'</button>').join('')+'</nav>'
            +'<div class="skin-grid" role="group" aria-label="20款气泡装扮"></div><footer class="skin-actions"><details class="skin-legacy"><summary>经典纯色</summary><div class="skin-legacy-colors">'
            +[['green','墨绿'],['blue','蓝'],['rose','玫红'],['ink','黑'],['amber','琥珀']].map(t=>'<button type="button" class="theme-dot" data-t="'+t[0]+'" data-legacy-skin="'+t[0]+'" aria-label="使用经典'+t[1]+'"></button>').join('')
            +'</div></details><button type="button" class="td-btn" data-skin-apply>使用这款</button></footer></section>');
        const dialog=document.getElementById('account-tools-dialog');dialog.classList.add('skin-dialog');refresh(dialog);
        const wardrobe=dialog.querySelector('.bubble-wardrobe');
        wardrobe.addEventListener('change',e=>{if(e.target.matches('[data-skin-motion]')){motion=e.target.checked;try{localStorage.setItem('QINGSU_BUBBLE_MOTION',motion?'on':'off');}catch(err){}syncMotion();}});
        wardrobe.addEventListener('click',async e=>{
            const pick=e.target.closest('[data-pick-skin]'),tab=e.target.closest('[data-skin-category]');
            if(pick){selected=pick.dataset.pickSkin;refresh(dialog);return;}
            if(tab){category=tab.dataset.skinCategory;refresh(dialog);return;}
            const apply=e.target.closest('[data-skin-apply]'),reset=e.target.closest('[data-legacy-skin]');
            if(!apply&&!reset)return;
            wardrobe.querySelectorAll('.skin-actions button').forEach(b=>b.disabled=true);
            const ok=await pickBubbleTheme(reset?reset.dataset.legacySkin:selected);
            if(!ok&&dialog.isConnected)wardrobe.querySelectorAll('.skin-actions button').forEach(b=>b.disabled=false);
        });
    }
    let observer=null;const observed=new Set();
    function watch(root) {
        syncMotion();
        if(!window.IntersectionObserver){root.querySelectorAll('[data-skin]').forEach(el=>el.classList.add('skin-visible'));return;}
        if(!observer)observer=new IntersectionObserver(entries=>entries.forEach(e=>e.target.classList.toggle('skin-visible',e.isIntersecting)),{rootMargin:'40px'});
        for(const el of observed)if(!el.isConnected){observer.unobserve(el);observed.delete(el);}
        root.querySelectorAll('[data-skin]').forEach(el=>{if(!observed.has(el)){observed.add(el);observer.observe(el);}});
    }
    window.QSBubbles={items,get,decor,preview,open,watch,has:id=>!!get(id)};
})();
