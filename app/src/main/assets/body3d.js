/* 轻塑 · 3D 人体动作渲染层
 *
 * 为什么要有这个文件：以前所谓"3D 演示"是把 17 个 2D 关节点画成一堆球再伪透视，
 * 所以看着臃肿、转起来更别扭。这里换成真正的骨骼网格：
 *   - 模型：Khronos glTF-Sample-Models / CesiumMan（CC-BY 4.0，见 models/CREDITS.md）
 *   - 姿态：从 exercise_poses.json 的 2D 关节点重建方向；骨长一律用模型自身的，
 *           所以怎么动都不会把身体拉长压扁
 *   - 求解：逐骨做 "绑定轴方向 -> 目标方向" 的最短弧四元数，在父骨已解出的空间里施加
 *
 * 任何一步失败（WebGL 不可用、模型加载失败、骨骼对不上、绑定姿态不对）都会把 status
 * 置为 'unavailable' 并带上原因，由 app.js 退回原来的 2D 画块法——不能白屏。
 */
import * as THREE from './vendor/three.module.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';

const MODEL_URL = 'models/cesium_man.glb';
const BODY_SCALE = 1.72;              // 归一化后的身高（米）
const SHOULDER_HALF = 0.10;           // 左右肢体分离
const HIP_HALF = 0.045;

/* 一根骨是"从自己的起点关节伸向子骨的起点"，所以：
     上臂骨(起点=肩) 用 肩->肘 转；前臂骨(起点=肘) 用 肘->腕 转。
   曾经把语义角色直接当关节用，整体错了一格：上臂和大腿永远不转，人就蜷成一团。 */
const BONES = [
    ['pelvis',      'Skeleton_torso_joint_1', 'pelvis',  'sternum'],
    ['spine',       'Skeleton_torso_joint_2', 'pelvis',  'sternum'],
    ['chest',       'torso_joint_3',          'sternum', 'neck'],
    ['neck',        'Skeleton_neck_joint_1',  'neck',    'head'],
    ['head',        'Skeleton_neck_joint_2',  'neck',    'head'],
    ['r_upper_arm', 'Skeleton_arm_joint_R',      'r_shoulder', 'r_elbow'],
    ['r_forearm',   'Skeleton_arm_joint_R__2_',  'r_elbow',    'r_wrist'],
    ['r_hand',      'Skeleton_arm_joint_R__3_',  null, null],
    ['l_upper_arm', 'Skeleton_arm_joint_L__4_',  'l_shoulder', 'l_elbow'],
    ['l_forearm',   'Skeleton_arm_joint_L__3_',  'l_elbow',    'l_wrist'],
    ['l_hand',      'Skeleton_arm_joint_L__2_',  null, null],
    ['r_thigh',     'leg_joint_R_1', 'r_hip',  'r_knee'],
    ['r_shin',      'leg_joint_R_2', 'r_knee', 'r_ankle'],
    ['r_foot',      'leg_joint_R_3', null, null],
    ['l_thigh',     'leg_joint_L_1', 'l_hip',  'l_knee'],
    ['l_shin',      'leg_joint_L_2', 'l_knee', 'l_ankle'],
    ['l_foot',      'leg_joint_L_3', null, null]
];
/* 解算顺序从躯干到四肢、从近端到远端，子骨才能读到父骨刚写好的世界旋转 */
const SOLVE_ORDER = ['pelvis', 'spine', 'chest', 'neck', 'head',
    'r_upper_arm', 'r_forearm', 'r_hand',
    'l_upper_arm', 'l_forearm', 'l_hand',
    'r_thigh', 'r_shin', 'r_foot',
    'l_thigh', 'l_shin', 'l_foot'];

/* 关节 -> 起点就是该关节的那根骨（用来取关节世界坐标） */
const JOINT_BONE = {
    pelvis: 'pelvis', sternum: 'chest', neck: 'neck', head: 'head',
    r_shoulder: 'r_upper_arm', r_elbow: 'r_forearm', r_wrist: 'r_hand',
    l_shoulder: 'l_upper_arm', l_elbow: 'l_forearm', l_wrist: 'l_hand',
    r_hip: 'r_thigh', r_knee: 'r_shin', r_ankle: 'r_foot',
    l_hip: 'l_thigh', l_knee: 'l_shin', l_ankle: 'l_foot'
};

const BONE_BY_NAME = {};
BONES.forEach(b => { BONE_BY_NAME[b[0]] = b; });

const State = {
    status: 'idle',                 // idle | loading | ready | unavailable
    reason: '',
    renderer: null, scene: null, camera: null, root: null,
    bones: {},                      // 语义名 -> Bone
    bindBoneQuat: {},               // 语义名 -> 绑定时世界四元数
    bindBoneLocal: {},              // 语义名 -> 绑定时局部四元数（不动这根骨头时该用它）
    bindJoint: {},                  // 关节名 -> 绑定时世界坐标
    markers: null, rig: null, rigJoints: null, jointWorld: {},
    yaw: Math.PI / 2, pitch: 0.1, camR: 0, camWant: 0, camY: 0.9, camCenter: [0, 0, 0], badFrame: null,
    frameMs: 0, triangles: 0, drawCalls: 0, solved: 0, frames: 0, nanBones: 0
};

const _dir = new THREE.Vector3(), _bindDir = new THREE.Vector3();
const _q = new THREE.Quaternion(), _pq = new THREE.Quaternion(), _pqInv = new THREE.Quaternion();
const _v = new THREE.Vector3(), _v2 = new THREE.Vector3();
const pts = [], ptNames = [];

function fail(reason) {
    State.status = 'unavailable';
    State.reason = reason;
    console.warn('[Body3D] 退回 2D 画块演示：' + reason);
}

function hasWebGL(canvas) {
    try { return !!(canvas.getContext('webgl2') || canvas.getContext('webgl')); }
    catch (e) { return false; }
}

/* ---------- 模型归一化：Y 朝上、脚在 0、水平居中、身高 BODY_SCALE ---------- */

function fitModelToScene() {
    const model = State.root.children[0];
    State.root.rotation.set(0, 0, 0);
    State.root.scale.set(1, 1, 1);
    State.root.position.set(0, 0, 0);
    State.root.updateMatrixWorld(true);

    // 谁最长谁就是"上"。有些导出已经在根节点上做过 Z->Y（CesiumMan 带一个 Z_UP 节点），
    // 再凭印象转一次会把人放倒，画面里就只剩一小截。
    const size0 = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
    if (size0.z >= size0.y && size0.z >= size0.x) State.root.rotation.x = -Math.PI / 2;
    else if (size0.x >= size0.y && size0.x >= size0.z) State.root.rotation.z = -Math.PI / 2;

    State.root.updateMatrixWorld(true);
    let box = new THREE.Box3().setFromObject(model);
    const h = Math.max(box.getSize(new THREE.Vector3()).y, 1e-3);
    State.root.scale.setScalar(BODY_SCALE / h);

    State.root.updateMatrixWorld(true);
    box = new THREE.Box3().setFromObject(model);
    const c = box.getCenter(new THREE.Vector3());
    State.root.position.set(-c.x, -box.min.y, -c.z);
    State.scene.updateMatrixWorld(true);
}

/* ---------- 2D 关节 -> 3D 关节 ---------- */

/* exercise_poses.json 的坐标已归一化且 y 向下。
   sagittal（矢状面）＝从侧面看：屏幕横轴是身体前后、纵轴是上下；
   frontal（冠状面）＝从正面看：屏幕横轴是身体左右。左右肢体沿第三轴分开。 */
function poseTo3D(pose, plane) {
    const out = {};
    const lateral = role => {
        const sign = role[0] === 'l' ? 1 : (role[0] === 'r' ? -1 : 0);
        const half = (role.includes('shoulder') || role.includes('elbow') || role.includes('wrist'))
            ? SHOULDER_HALF : HIP_HALF;
        return sign * half;
    };
    for (const role of Object.keys(pose)) {
        const p = pose[role];
        if (!p || p.length < 2) continue;
        if (!isFinite(p[0]) || !isFinite(p[1])) continue;
        const a = (p[0] - 0.5) * BODY_SCALE;
        const b = -(p[1] - 0.5) * BODY_SCALE;
        const off = lateral(role);
        out[role] = (plane === 'frontal')
            ? new THREE.Vector3(a + off * 0.35, b, off)
            : new THREE.Vector3(off, b, a);
    }
    return out;
}

/* 外壳尺寸（米）。蒙皮网格是 2013 年的测试人台，一摆躺姿就塌成一团，
   所以这里只借它的骨骼（骨长、关节位置都是真的），外壳按关节自己画：
   骨头=圆柱、关节=球，粗细由这张表控制，不会再出现"臃肿成一坨"。 */
const BONE_R = {
    pelvis: 0.070, spine: 0.074, chest: 0.080, neck: 0.032,
    r_upper_arm: 0.034, r_forearm: 0.028, l_upper_arm: 0.034, l_forearm: 0.028,
    r_thigh: 0.052, r_shin: 0.040, l_thigh: 0.052, l_shin: 0.040
};
const JOINT_R = {
    pelvis: 0.076, sternum: 0.082, neck: 0.040, head: 0.092,
    r_shoulder: 0.048, l_shoulder: 0.048, r_elbow: 0.032, l_elbow: 0.032,
    r_wrist: 0.026, l_wrist: 0.026, r_hip: 0.052, l_hip: 0.052,
    r_knee: 0.040, l_knee: 0.040, r_ankle: 0.030, l_ankle: 0.030
};
const SHELL_PAD = 0.10;               // 外壳比关节最粗的一档再探出去的距离

/* ---------- 骨骼求解 ---------- */

function solve(target) {
    State.solved = 0;
    for (const name of SOLVE_ORDER) {
        const bone = State.bones[name];
        if (!bone) continue;
        const def = BONE_BY_NAME[name];
        const fromJoint = def[2], toJoint = def[3];
        if (!fromJoint || !toJoint || !target[fromJoint] || !target[toJoint]) {
            /* 这一帧没有该骨的目标：保持"绑定的局部旋转"。用世界四元数会把父链
               的旋转重复算一次，手/脚这类骨就会歪出去（模型根节点带 Z_UP 旋转）。 */
            bone.quaternion.copy(State.bindBoneLocal[name]);
            continue;
        }
        _dir.copy(target[toJoint]).sub(target[fromJoint]);
        _bindDir.copy(State.bindJoint[toJoint]).sub(State.bindJoint[fromJoint]);
        if (_dir.lengthSq() < 1e-8 || _bindDir.lengthSq() < 1e-8) continue;
        _dir.normalize(); _bindDir.normalize();

        /* 世界系摆位：Δ = 从绑定轴转到目标轴的最短弧；
           局部旋转 = 父骨当前世界旋转的逆 · Δ · 该骨绑定时世界旋转。
           只改指向、不引入额外自旋，骨长完全由模型决定。 */
        _q.setFromUnitVectors(_bindDir, _dir);
        bone.parent.getWorldQuaternion(_pq);
        _pqInv.copy(_pq).invert();
        bone.quaternion.copy(_pqInv).multiply(_q).multiply(State.bindBoneQuat[name]);
        if (!isFinite(bone.quaternion.x) || !isFinite(bone.quaternion.w)) {
            /* 父链已经带毒（四元数非有限）时，NaN 会顺着骨骼树往下染，
               一帧之内 15 根骨头全变 NaN，关节包围盒直接飞到 5e8。
               退回这一根的绑定旋转，并把中毒次数报出来。 */
            State.nanBones++;
            bone.quaternion.copy(State.bindBoneLocal[name]);
        }
        bone.parent.updateMatrixWorld(true);
        bone.updateMatrixWorld(true);
        State.solved++;
    }
}

/* ---------- 人体外壳 ---------- */

const _up = new THREE.Vector3(0, 1, 0);

function buildRig() {
    const mat = new THREE.MeshStandardMaterial({ color: 0xEAF0F8, roughness: 0.55, metalness: 0.04 });
    const tube = new THREE.CylinderGeometry(1, 1, 1, 14);
    const ball = new THREE.SphereGeometry(1, 18, 14);
    State.rig = [];
    State.rigJoints = [];
    for (const def of BONES) {
        const r = BONE_R[def[0]];
        if (!r) continue;                       // 手/脚末端没有独立骨长，交给关节球
        const mesh = new THREE.Mesh(tube, mat);
        mesh.frustumCulled = false;
        State.scene.add(mesh);
        State.rig.push({ from: def[2], to: def[3], mesh: mesh, r: r });
    }
    for (const joint of Object.keys(JOINT_R)) {
        const mesh = new THREE.Mesh(ball, mat);
        mesh.frustumCulled = false;
        State.scene.add(mesh);
        State.rigJoints.push({ joint: joint, mesh: mesh, r: JOINT_R[joint] });
    }
}

/** 每帧按"解算之后的关节世界坐标"重摆外壳。
    骨骼只管指向，外壳跟着关节走，蒙皮塌陷就不可能出现。 */
function updateRig() {
    if (!State.rig) return;
    for (const item of State.rig) {
        const a = State.jointWorld[item.from], b = State.jointWorld[item.to];
        if (!a || !b) { item.mesh.visible = false; continue; }
        _dir.copy(b).sub(a);
        const len = _dir.length();
        if (!(len > 1e-4)) { item.mesh.visible = false; continue; }
        item.mesh.visible = true;
        item.mesh.position.copy(a).addScaledVector(_dir, 0.5);
        _dir.multiplyScalar(1 / len);
        item.mesh.quaternion.setFromUnitVectors(_up, _dir);
        item.mesh.scale.set(item.r, len, item.r);
    }
    for (const item of State.rigJoints) {
        let p = State.jointWorld[item.joint];
        if (!p) { item.mesh.visible = false; continue; }
        item.mesh.visible = true;
        if (item.joint === 'head') {
            // head 关节在颅顶：球要落在颈→头这一段偏上的位置，不然脑袋会浮在头顶外
            const n = State.jointWorld.neck;
            if (n) { _bindDir.copy(p).sub(n).multiplyScalar(0.62); p = _v2.copy(n).add(_bindDir); }
        }
        item.mesh.position.copy(p);
        item.mesh.scale.setScalar(item.r);
    }
}

/* ---------- 场景 ---------- */

function buildScene(canvas) {
    // preserveDrawingBuffer：自动化要靠像素数一数到底有没有画出人形。
    // 不开的话读回来永远是空的，"没画"和"没测"长得一模一样。
    State.renderer = new THREE.WebGLRenderer({
        canvas, antialias: true, alpha: true, preserveDrawingBuffer: true
    });
    State.renderer.setClearAlpha(0);
    State.scene = new THREE.Scene();
    State.camera = new THREE.PerspectiveCamera(34, 1, 0.05, 30);

    const key = new THREE.DirectionalLight(0xFFFFFF, 2.2);
    key.position.set(1.8, 2.6, 2.2);
    const fill = new THREE.DirectionalLight(0x9FB6D9, 0.75);
    fill.position.set(-2.2, 1.1, -1.0);
    const rim = new THREE.DirectionalLight(0x34D399, 1.0);
    rim.position.set(0, 1.4, -2.8);
    State.scene.add(key, fill, rim, new THREE.HemisphereLight(0xE6F0FF, 0x1B2434, 0.9));

    // 脚下的接触阴影，让人体"站住"而不是浮在黑背景里
    const disc = new THREE.Mesh(
        new THREE.CircleGeometry(0.46, 44),
        new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.32 })
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.004;
    State.scene.add(disc);
}

/* 发力标记：贴在目标肌群所在关节上的半透明球。
   它是"标记"不是"肌肉网格"，所以文案只说发力部位，不假装解剖精度。 */
const MUSCLE_JOINTS = {
    chest: ['sternum', 'r_shoulder', 'l_shoulder'],
    core: ['pelvis', 'sternum'],
    glutes: ['pelvis', 'r_hip', 'l_hip'],
    quads: ['r_knee', 'l_knee'],
    hamstrings: ['r_hip', 'l_hip', 'r_knee', 'l_knee'],
    calves: ['r_ankle', 'l_ankle'],
    shoulders: ['r_shoulder', 'l_shoulder', 'neck'],
    arms: ['r_elbow', 'l_elbow'],
    back: ['sternum', 'neck'],
    full_body: ['sternum', 'pelvis', 'r_knee', 'l_knee', 'r_elbow', 'l_elbow']
};

function buildMarkers() {
    const group = new THREE.Group();
    for (const joint of Object.keys(MUSCLE_JOINTS).reduce((a, k) => a.concat(MUSCLE_JOINTS[k]), [])) {
        if (group.children.some(m => m.userData.joint === joint)) continue;
        const m = new THREE.Mesh(
            new THREE.SphereGeometry(0.055, 16, 12),
            new THREE.MeshBasicMaterial({ color: 0xF59E0B, transparent: true, opacity: 0, depthWrite: false })
        );
        m.userData.joint = joint;
        group.add(m);
    }
    State.scene.add(group);
    State.markers = group;
}

function updateMarkers(active) {
    if (!State.markers) return;
    const lit = new Set();
    (active || []).forEach(k => (MUSCLE_JOINTS[String(k).toLowerCase()] || []).forEach(j => lit.add(j)));
    State.markers.children.forEach(m => {
        const want = lit.has(m.userData.joint) ? 0.5 : 0;
        m.material.opacity += (want - m.material.opacity) * 0.18;   // 缓入缓出，不闪
        const bone = State.bones[JOINT_BONE[m.userData.joint]];
        if (bone) { bone.getWorldPosition(_v); m.position.copy(_v); }
    });
}

/* ---------- 对外接口 ---------- */

const Body3D = {
    get status() { return State.status; },
    get reason() { return State.reason; },
    stats: function () {
        const c = State.camera;
        return {
            status: State.status, reason: State.reason,
            frameMs: +State.frameMs.toFixed(1), triangles: State.triangles,
            drawCalls: State.drawCalls, solvedBones: State.solved,
            bones: Object.keys(State.bones).length, frames: State.frames,
            nanBones: State.nanBones, badFrame: State.badFrame,
            // 相机与焦点：判据要能算"体长轴和视线是不是接近平行"，
            // 接近平行时什么动作都会画成一团，只看 triangles>0 是查不出来的。
            view: c ? {
                yaw: +State.yaw.toFixed(3), r: +State.camR.toFixed(2),
                px: +c.position.x.toFixed(2), py: +c.position.y.toFixed(2), pz: +c.position.z.toFixed(2),
                cx: +State.camCenter[0].toFixed(3), cy: +State.camCenter[1].toFixed(3), cz: +State.camCenter[2].toFixed(3)
            } : null
        };
    },

    init: async function (canvas) {
        if (State.status === 'ready' || State.status === 'loading') return State.status;
        if (!canvas) { fail('找不到 3D 画布'); return State.status; }
        if (!hasWebGL(canvas)) { fail('这台设备拿不到 WebGL 上下文'); return State.status; }
        State.status = 'loading';
        try {
            buildScene(canvas);
            const gltf = await new GLTFLoader().loadAsync(MODEL_URL);
            State.root = new THREE.Group();
            State.root.add(gltf.scene);
            State.scene.add(State.root);
            fitModelToScene();

            const byName = {};
            gltf.scene.traverse(o => { if (o.isBone) byName[o.name] = o; });
            const missing = BONES.filter(b => !byName[b[1]]).map(b => b[1]);
            if (missing.length) { fail('模型缺少骨骼：' + missing.slice(0, 5).join(', ')); return State.status; }

            // 蒙皮网格只用来拿骨骼，不参与显示（见 BONE_R 上方注释）。
            gltf.scene.traverse(o => { if (o.isMesh) o.visible = false; });
            BONES.forEach(b => { State.bones[b[0]] = byName[b[1]]; });

            State.scene.updateMatrixWorld(true);
            for (const name of SOLVE_ORDER) {
                State.bindBoneQuat[name] = State.bones[name].getWorldQuaternion(new THREE.Quaternion());
                State.bindBoneLocal[name] = State.bones[name].quaternion.clone();
            }
            for (const joint of Object.keys(JOINT_BONE)) {
                State.bones[JOINT_BONE[joint]].getWorldPosition(_v);
                State.bindJoint[joint] = _v.clone();
            }
            // 绑定姿态本身要站得住：头在骨盆上方、膝在髋踝之间。
            // 不校验的话映射或朝向写错也会"正常渲染"，只是画出来是个蜷起来的团。
            const bj = State.bindJoint;
            if (!(bj.head.y > bj.pelvis.y)) {
                fail('绑定姿态不对（头不在骨盆上方），模型朝向或骨骼映射有误');
                return State.status;
            }
            if (!(bj.r_knee.y < bj.r_hip.y && bj.r_knee.y > bj.r_ankle.y)) {
                fail('绑定姿态不对（右膝不在髋与踝之间），左右或上下映射反了');
                return State.status;
            }
            buildRig();
            buildMarkers();

            State.status = 'ready';
            Body3D.resize(canvas);
            return State.status;
        } catch (e) {
            fail('模型或渲染器初始化失败：' + (e && e.message ? e.message : e));
            return State.status;
        }
    },

    setPose: function (pose, plane, yawRad, muscles) {
        if (State.status !== 'ready') return false;
        const t0 = performance.now();
        const target = poseTo3D(pose, plane);
        solve(target);
        if (State.solved === 0) return false;          // 一根都没驱动，宁可退回画块
        State.root.updateMatrixWorld(true);
        updateMarkers(muscles);
        /* 2D 画块法里的 yaw 是"人体自转角"，不是相机环绕角：直接当相机角用，
           默认 24° 会几乎沿着体长轴看过去，什么姿势都会压成一团。矢状面动作要
           从侧面看，所以相机方位 = 自转角 + 90°。 */
        const frontal = (plane === 'frontal');
        if (typeof yawRad === 'number' && isFinite(yawRad))
            State.yaw = frontal ? yawRad : yawRad + Math.PI / 2;

        /* 取景跟随"当前这一帧的真实姿态范围"：臀桥是躺着的，整体只有半米高，
           按站姿身高取景就会缩成一小团。必须量解算之后的关节世界坐标——
           target 只用来给方向，身体真正落在哪儿由模型骨骼决定，拿 target 的
           包围盒对焦会整段对歪。 */
        State.root.updateMatrixWorld(true);
        let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9, minZ = 1e9, maxZ = -1e9, seen = 0;
        pts.length = 0; ptNames.length = 0;
        for (const joint of Object.keys(JOINT_BONE)) {
            const bone = State.bones[JOINT_BONE[joint]];
            if (!bone) continue;
            bone.getWorldPosition(_v);
            seen++;
            pts.push(_v.x, _v.y, _v.z); ptNames.push(joint);
            State.jointWorld[joint] = _v.clone();
            if (_v.x < minX) minX = _v.x; if (_v.x > maxX) maxX = _v.x;
            if (_v.y < minY) minY = _v.y; if (_v.y > maxY) maxY = _v.y;
            if (_v.z < minZ) minZ = _v.z; if (_v.z > maxZ) maxZ = _v.z;
        }
        if (!seen) return false;
        const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, cz = (minZ + maxZ) / 2;
        /* 取景用包围球，不用包围盒最长边：躺姿的体长轴会随相机方位转到屏幕纵深方向，
           按某一条边算必然把头顶或脚裁出去。半径除以"较窄那侧半角的正弦"，
           怎么转身体都完整在画面里。 */
        let rad = 0.35, far = null;
        for (let i = 0; i < pts.length; i += 3) {
            const d = Math.hypot(pts[i] - cx, pts[i + 1] - cy, pts[i + 2] - cz);
            if (d > rad) { rad = d; far = { joint: ptNames[i / 3], at: [+pts[i].toFixed(2), +pts[i + 1].toFixed(2), +pts[i + 2].toFixed(2)] }; }
        }
        const vfov = State.camera.fov * Math.PI / 180;
        const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (State.camera.aspect || 1));
        /* SHELL_PAD：外壳是画在关节之间的圆柱与球，脑袋那颗球能比关节再探出 9cm。
           只按关节包围球取景，跪姿这种"关节本身很紧凑"的动作就会把头顶裁掉
           （实测 ndcMax 1.25）。 */
        const wantRaw = ((rad + SHELL_PAD) * 1.02) / Math.sin(Math.min(vfov, hfov) / 2);
        if (!(wantRaw > 0.9) || wantRaw > 12) {
            /* 算出荒谬的取景距离＝这一帧的关节包围有问题。用回上一帧的距离，
               但必须把异常留在 stats 里：悄悄画一张歪的，比画不出来更难查。 */
            if (!State.badFrame) State.badFrame = {
                want: +wantRaw.toFixed(1), rad: +rad.toFixed(2), seen: seen,
                fov: State.camera.fov, aspect: +State.camera.aspect.toFixed(3), far: far,
                nan: pts.filter(Number.isNaN).length, solved: State.solved,
                frame: State.frames, yaw: +State.yaw.toFixed(3)
            };
        } else {
            State.camWant = wantRaw;
            State.camR = State.camR ? State.camR + (wantRaw - State.camR) * 0.08 : wantRaw;
        }
        const r = State.camR;
        State.camY = cy;
        State.camCenter[0] = cx; State.camCenter[1] = cy; State.camCenter[2] = cz;
        State.camera.position.set(
            cx + Math.sin(State.yaw) * r * Math.cos(State.pitch),
            cy + Math.sin(State.pitch) * r * 0.35,
            cz + Math.cos(State.yaw) * r * Math.cos(State.pitch)
        );
        State.camera.lookAt(cx, cy, cz);
        updateRig();
        State.renderer.render(State.scene, State.camera);
        State.drawCalls = State.renderer.info.render.calls;
        State.triangles = State.renderer.info.render.triangles;
        State.frameMs = performance.now() - t0;
        State.frames++;
        return true;
    },

    /* 关节世界坐标与骨长：给自动化断言用。
       只看"有没有画东西"证明不了动画生效，必须能证明关节在动、骨长没被拉变形。 */
    joints: function () {
        if (State.status !== 'ready') return null;
        State.scene.updateMatrixWorld(true);
        const out = {};
        for (const joint of Object.keys(JOINT_BONE)) {
            const bone = State.bones[JOINT_BONE[joint]];
            if (!bone) continue;
            bone.getWorldPosition(_v);
            out[joint] = [+_v.x.toFixed(4), +_v.y.toFixed(4), +_v.z.toFixed(4)];
        }
        return out;
    },

    boneLengths: function () {
        if (State.status !== 'ready') return null;
        const out = {};
        for (const name of SOLVE_ORDER) {
            const def = BONE_BY_NAME[name];
            if (!def[2] || !def[3]) continue;
            const a = State.bindJoint[def[2]], b = State.bindJoint[def[3]];
            if (a && b) out[name] = +a.distanceTo(b).toFixed(4);
        }
        return out;
    },

    /* 同帧渲染并回读像素：WebGL 画布在下一帧之前可能被合成器清空，
       分开两次调用读回来永远是 0，会把"没测到"看成"没画出"。 */
    selfTest: function (pose, plane, yawRad) {
        if (State.status !== 'ready') return { ok: false, reason: State.status };
        const p = pose || poseFromTableSelfTest();
        if (!p) return { ok: false, reason: '没有姿态数据' };
        // 允许自动化按"屏幕上当前这个相机"来验，而不是永远验一个参考机位。
        const yaw = (typeof yawRad === 'number' && isFinite(yawRad)) ? yawRad : 0;
        if (!Body3D.setPose(p, plane || 'sagittal', yaw, [])) return { ok: false, reason: 'setPose 失败' };
        /* 取景是逐帧逼近的（0.08/帧），刚换动作时相机还在路上。自测要量"停稳之后"
           的画面：第一遍拿到这一帧的目标距离，把距离钉过去再渲染一遍。
           只钉一次等于拿"上一帧"的距离量"这一帧"的姿势，换动作时必然测歪。 */
        if (State.camWant) {
            State.camR = State.camWant;
            if (!Body3D.setPose(p, plane || 'sagittal', yaw, [])) return { ok: false, reason: 'setPose 第二遍失败' };
        }
        const gl = State.renderer.getContext();
        const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
        const buf = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
        let n = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
        for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            if (buf[i + 3] > 10 && (buf[i] + buf[i + 1] + buf[i + 2]) > 90) {
                n++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
            }
        }
        const coverage = 100 * n / (w * h);
        /* 墨迹面积占比不适合当判据：站姿又高又瘦、跪姿张成一大片，
           同一个"画得好"的分数能差好几十。改量"画面被用掉了多少"——
           取景本来就是按包围球贴边的，画得对就必然占满长边。 */
        const fill = x1 > x0 ? 100 * Math.max((x1 - x0) / w, (y1 - y0) / h) : 0;
        let alphaAny = 0;
        for (let i = 3; i < buf.length; i += 4) if (buf[i] > 10) alphaAny++;
        const ci = ((h >> 1) * w + (w >> 1)) * 4;
        /* 两个"看着不对"的量化口径：
           ndcMax>1 ＝ 有肢体被裁到画面外；endOn≈1 ＝ 相机几乎沿体长轴看过去，
           什么姿势都会压成一团。只判 coverage>6 时这两种都能绿。 */
        let ndcMax = 0, endOn = 0;
        State.camera.updateMatrixWorld(true);
        const jp = Body3D.joints();
        if (jp && jp.head && jp.r_ankle) {
            const ax = jp.head[0] - jp.r_ankle[0], ay = jp.head[1] - jp.r_ankle[1], az = jp.head[2] - jp.r_ankle[2];
            const al = Math.hypot(ax, ay, az) || 1;
            const cp = State.camera.position;
            const fx = cp.x - State.camCenter[0], fy = cp.y - State.camCenter[1], fz = cp.z - State.camCenter[2];
            const fl = Math.hypot(fx, fy, fz) || 1;
            endOn = Math.abs((ax * fx + ay * fy + az * fz) / (al * fl));
            for (const k in jp) {
                _v.set(jp[k][0], jp[k][1], jp[k][2]).project(State.camera);
                ndcMax = Math.max(ndcMax, Math.abs(_v.x), Math.abs(_v.y));
            }
        }
        return { ok: coverage > 3 && fill > 45 && ndcMax <= 0.99, coverage: +coverage.toFixed(1),
                 fill: +fill.toFixed(1),
                 box: x1 > 0 ? [x1 - x0, y1 - y0] : null, buffer: w + 'x' + h,
                 ndcMax: +ndcMax.toFixed(3), endOn: +endOn.toFixed(3),
                 alphaAny: alphaAny, centerPx: [buf[ci], buf[ci + 1], buf[ci + 2], buf[ci + 3]],
                 cam: [+State.camera.position.x.toFixed(2), +State.camera.position.y.toFixed(2), +State.camera.position.z.toFixed(2)],
                 aspect: +(State.camera.aspect || 0).toFixed(3), r: +State.camR.toFixed(2),
                 bad: State.badFrame,
                 joints: jp };
    },

    resize: function (canvas) {
        if (!State.renderer || !canvas) return;
        const w = canvas.clientWidth || 340, h = canvas.clientHeight || 360;
        State.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        State.renderer.setSize(w, h, false);
        State.camera.aspect = w / h;
        State.camera.updateProjectionMatrix();
    },

    dispose: function () {
        try { if (State.renderer) State.renderer.dispose(); } catch (e) {}
        State.renderer = null; State.scene = null; State.bones = {};
        State.status = 'idle';
    }
};

function poseFromTableSelfTest() {
    try { return (typeof poseFromTable === 'function') ? poseFromTable(null, 'bridge', 0.3) : null; }
    catch (e) { return null; }
}
window.Body3D = Body3D;
export default Body3D;
