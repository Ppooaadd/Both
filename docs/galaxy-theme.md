# 은하계(Galaxy) 테마

기존 레이아웃은 그대로 두고 색·질감·배경·움직임만 덮어씌운 스킨이다.

| 구성 | 파일 | 역할 |
|---|---|---|
| 우주 배경 | `apps/web/src/lib/galaxy/scene.ts` | Three.js. 반짝이는 별, 나선 은하, 성운, 가끔 지나가는 유성. 커서 방향으로 시점이 기울고 커서 근처 별이 밝아짐 |
| 클릭 이펙트 | `apps/web/src/lib/galaxy/clickBurst.ts` | 클릭 지점에 빛 파동 + 별가루. `.galaxy-neon-btn` 클릭은 더 크게 |
| 스크롤 등장 | `apps/web/src/lib/galaxy/scrollReveal.ts` | GSAP ScrollTrigger. `.animate-fade-up` 요소가 흐림이 풀리며 떠오름 |
| 실행 컴포넌트 | `apps/web/src/components/galaxy/GalaxyLayer.tsx` | 캔버스 2개를 두고 위 세 모듈을 첫 화면 이후 지연 로드 |
| 스킨 CSS | `apps/web/src/styles/galaxy.css` | 우주 색 토큰, `.galaxy-glass-panel`, `.galaxy-neon-btn`, 등장 전 상태 |

## 1. 적용 위치 (이 사이트, Next.js)

Next.js App Router에는 `index.html`이 없다. 그 역할은 `src/app/layout.tsx`가 한다.

1. **패키지**: `npm install three gsap` (`@types/three`는 개발 의존성). CDN 대신 npm으로 설치해 버전이 고정되고 번들러가 필요한 부분만 싣는다.
2. **CSS**: `src/app/globals.css` 맨 위 `@import`들 바로 아래에 `@import "../styles/galaxy.css";`
3. **레이아웃**: `src/app/layout.tsx`
   - `<html className="galaxy ...">`: 우주 색 토큰을 켠다.
   - `<head>`의 짧은 인라인 스크립트: 등장 애니메이션이 준비되면 `.animate-fade-up`을 미리 숨긴다. 4초 안에 스크립트가 시작되지 않으면 숨김을 풀어 내용이 사라지지 않게 한다.
   - `<body>` 맨 앞에 `<GalaxyLayer />`: `#galaxy-canvas`(`position: fixed; z-index: -1`)와 `#galaxy-click-layer`(`z-index: 9999; pointer-events: none`)를 만든다.

이미 적용된 곳: 모든 `Card`에 `galaxy-glass-panel animate-fade-up`, 기본 `Button`에 `galaxy-neon-btn`, 상단 헤더에 유리 효과, 홈 화면 소개 문단과 단계 목록에 `animate-fade-up`. 악보 미리보기는 읽기 쉽도록 흰 종이 배경을 유지한다.

## 2. 클래스 사용법

```html
<div class="galaxy-glass-panel rounded-xl p-6">반투명 유리 패널</div>
<button class="galaxy-neon-btn rounded-md px-4 py-2">네온 버튼</button>
<section class="animate-fade-up">스크롤하면 떠오르는 영역</section>
```

세 클래스는 CSS `components` 레이어에 있어서 같은 요소의 Tailwind 유틸리티(`sticky`, `rounded-*`, `bg-*`)가 이긴다. 레이아웃이 바뀌지 않는다.

## 3. 밝기·투명도 조절

`:root`(또는 원하는 조상 요소)에서 CSS 변수로 조절한다.

```css
:root {
  --galaxy-opacity: 0.9; /* 우주 배경 밝기 0~1. 0.5면 은은하게 */
  --glass-alpha: 0.42;   /* 유리 패널 채움 불투명도. 높일수록 글자가 또렷 */
  --glass-blur: 14px;    /* 유리 뒤 흐림 정도 */
}
```

캔버스는 `alpha: true`로 투명하게 그리고, 밝기는 캔버스의 CSS `opacity`(`--galaxy-opacity`)로 조절한다. 색 바탕은 `html.galaxy`의 배경 그라데이션이 맡는다.

## 성능과 접근성

- Three.js·GSAP는 첫 화면이 그려진 뒤 지연 로드된다.
- 모바일은 별 수를 줄이고(1.5천 + 은하 7천) 해상도 배율을 낮춘다.
- 프레임이 느려지면 해상도를 단계적으로 낮추고, 그래도 느리면 한 프레임씩 건너뛴다. 재생·진행률 같은 페이지 동작이 배경 때문에 밀리지 않게 하기 위해서다.
- 탭이 숨겨지면 렌더링을 멈춘다.
- 운영체제의 "동작 줄이기"가 켜져 있으면 배경은 정지 화면 한 장만 그리고, 클릭·스크롤 효과는 끈다.
- WebGL을 쓸 수 없으면 CSS 그라데이션 배경만 남는다.

## 일반 HTML 사이트에 붙일 때 (참고)

Next.js가 아닌 정적 `index.html`이라면:

1. `<head>` 안: `galaxy.css`를 `<link rel="stylesheet" href="galaxy.css">`로 연결하고, 위의 인라인 스크립트를 넣는다. `<html class="galaxy">`로 테마를 켠다.
2. `<body>` 맨 처음: `<canvas id="galaxy-canvas"></canvas><canvas id="galaxy-click-layer"></canvas>`
3. `</body>` 바로 앞: 모듈 스크립트로 라이브러리와 세 모듈을 불러 실행한다.

```html
<script type="importmap">
  { "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js",
      "gsap": "https://cdn.jsdelivr.net/npm/gsap@3.15.0/index.js",
      "gsap/ScrollTrigger": "https://cdn.jsdelivr.net/npm/gsap@3.15.0/ScrollTrigger.js"
  } }
</script>
<script type="module">
  import { createGalaxy } from "./galaxy/scene.js";
  import { createClickBurst } from "./galaxy/clickBurst.js";
  import { startScrollReveal } from "./galaxy/scrollReveal.js";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mobile = matchMedia("(max-width: 768px), (pointer: coarse)").matches;
  const bg = document.getElementById("galaxy-canvas");
  if (createGalaxy(bg, { reducedMotion: reduced, mobile })) bg.classList.add("is-ready");
  if (!reduced) {
    createClickBurst(document.getElementById("galaxy-click-layer"));
    startScrollReveal();
  }
</script>
```

`scene.js` 등은 `src/lib/galaxy/*.ts`를 `tsc`로 JavaScript로 변환한 파일이다(타입 표기만 빠진다).
