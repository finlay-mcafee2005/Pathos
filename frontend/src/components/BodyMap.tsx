// Front + back muscle map for the check-in. A thin body outline with each
// muscle group as its own rounded shape; sore ones light up blue. Each half is
// drawn once and mirrored. Front view: the runner's left is on the viewer's
// right (like facing a person); back view: same side as the viewer.

type Props = { selected: string[]; onToggle: (id: string) => void; labels: Record<string, string> };

// rounded rectangle path, for the ab blocks
function rr(x1: number, y1: number, x2: number, y2: number, r = 3): string {
  return `M${x1 + r},${y1} L${x2 - r},${y1} Q${x2},${y1} ${x2},${y1 + r} L${x2},${y2 - r} Q${x2},${y2} ${x2 - r},${y2} `
    + `L${x1 + r},${y2} Q${x1},${y2} ${x1},${y2 - r} L${x1},${y1 + r} Q${x1},${y1} ${x1 + r},${y1} Z`;
}

// outer contour of the left half, from the top of the head to the crotch
const CONTOUR =
  "M100,8 C90,8 86,16 86,27 C86,38 90,45 95,48 L94,56 C88,60 76,61 68,64 C58,67 53,76 52,88 "
  + "C50,102 48,118 48,132 C46,146 43,162 42,176 C41,190 41,200 40,208 C37,214 36,224 40,232 "
  + "C43,236 47,234 48,228 C50,222 51,214 52,208 C55,192 58,170 60,152 C62,138 63,120 64,108 "
  + "C65,102 67,100 69,104 C71,124 73,150 73,170 C72,184 70,196 70,206 C68,236 70,262 74,288 "
  + "C72,310 72,340 76,368 C74,376 70,384 74,390 C80,394 90,394 94,390 C96,384 95,378 94,370 "
  + "C96,346 97,320 96,296 C97,270 99,244 100,214";

const DELT = "M70,66 C60,68 55,76 55,86 C55,94 58,99 62,100 C64,90 67,80 72,72 Z";
const UPPER_ARM = "M56,104 C52,114 52,130 55,140 C58,145 62,144 63,138 C64,126 64,112 61,104 C59,101 57,101 56,104 Z";
const FOREARM = "M52,150 C47,162 46,178 47,196 C50,199 53,198 54,194 C56,180 58,164 59,150 C57,146 54,146 52,150 Z";

// [path(s) for the left half, id on the viewer's left, id on the viewer's right]
type Muscle = [string[], string, string];

const FRONT: Muscle[] = [
  [["M95,58 C88,61 80,62 74,64 C81,67 89,67 96,64 Z"], "traps", "traps"],
  [[DELT], "right_shoulder", "left_shoulder"],
  [["M98,70 C88,68 78,70 73,76 C70,84 72,94 78,99 C86,102 94,100 98,96 Z"], "chest", "chest"],
  [[UPPER_ARM], "right_bicep", "left_bicep"],
  [[FOREARM], "right_forearm", "left_forearm"],
  [[rr(89, 105, 98.5, 119), rr(89, 121, 98.5, 135), rr(89, 137, 98.5, 151), rr(89.5, 153, 98.5, 168, 4)], "abs", "abs"],
  [["M76,104 C74,120 76,140 80,160 C83,164 86,162 86,156 C86,138 86,120 86,106 C83,103 79,102 76,104 Z"], "obliques", "obliques"],
  [["M80,171 C78,179 80,188 86,194 C90,190 94,184 96,176 C92,172 86,170 80,171 Z"], "right_hip", "left_hip"],
  // IT band: the strip down the outside of the thigh
  [["M71,210 C69,232 70,258 74,282 C75.5,283.5 77,282.5 76.8,280 C74.6,258 74,232 75.2,210 C74,206.5 72,206.5 71,210 Z"],
    "right_itband", "left_itband"],
  [["M77.5,206 C74,226 74,252 78.5,278 C81,282 84,280 85,274 C86,252 85,226 84,206 C81.5,202.5 79,202.5 77.5,206 Z",
    "M87,200 C85,222 85,248 87,272 C89,278 93,278 94,272 C96,248 96,222 95,200 C92,196 89,196 87,200 Z"], "right_quad", "left_quad"],
  [["M97,206 C96,222 97,238 98,252 C99.5,250 99.6,232 99.6,210 C99,206 98,205 97,206 Z"], "right_adductor", "left_adductor"],
  // kneecap, between the quad and the shin
  [["M80.5,285 C79.5,290 80.5,295.5 83.5,298 C87,300 91,299.5 93,296.5 C94.6,292 94,286.5 92,283 C88,280 83.5,280.5 80.5,285 Z"],
    "right_knee", "left_knee"],
  [["M78,300 C76,320 77,342 80,362 C82,365 84,363 84,358 C84,338 84,318 83,300 C81,297 79,297 78,300 Z",
    "M88,300 C87,320 88,342 90,360 C92,363 94,361 94,356 C94,336 94,316 93,300 C91,297 89,297 88,300 Z"], "right_shin", "left_shin"],
];

const BACK: Muscle[] = [
  [["M100,50 C96,56 88,60 77,63 C86,66 94,70 98,78 L100,80 Z"], "traps", "traps"],
  [[DELT], "left_shoulder", "right_shoulder"],
  [["M73,76 C68,96 70,120 78,142 C82,146 86,144 86,138 C86,116 84,96 81,80 C79,76 76,75 73,76 Z",
    "M98,84 C92,84 87,86 85,91 C87,104 91,115 98,121 Z"], "upper_back", "upper_back"],
  [["M98,127 C92,127 88,131 87,137 C88,147 92,155 98,159 Z"], "lower_back", "lower_back"],
  [[UPPER_ARM], "left_tricep", "right_tricep"],
  [[FOREARM], "left_forearm", "right_forearm"],
  [["M74,151 C72,156 72,161 74,166 C79,164 84,163 88,163 C87,158 85,153 82,149 C79,147 76,148 74,151 Z"], "left_hip", "right_hip"],
  [["M99,170 C90,166 80,170 77,183 C74,197 78,209 88,213 C95,215 99,209 99,201 Z"], "glutes", "glutes"],
  [["M76,222 C72,244 74,266 80,284 C86,290 94,288 96,280 C98,262 98,240 97,222 C90,218 82,218 76,222 Z"], "left_hamstring", "right_hamstring"],
  [["M78,300 C72,316 74,336 82,350 C88,354 94,350 95,340 C96,326 95,312 93,300 C88,296 83,296 78,300 Z"], "left_calf", "right_calf"],
];

const MIRROR = "translate(200 0) scale(-1 1)";

function Figure({ x, muscles, selected, onToggle, labels }: {
  x: number; muscles: Muscle[]; selected: string[]; onToggle: (id: string) => void; labels: Record<string, string>;
}) {
  const half = (side: "l" | "r") => (
    <g transform={side === "r" ? MIRROR : undefined}>
      <path d={CONTOUR + " Z"} className="bm-body" />
      <path d={CONTOUR} className="bm-outline" />
      {muscles.map(([paths, leftId, rightId]) => {
        const id = side === "l" ? leftId : rightId;
        const on = selected.includes(id);
        return (
          <g key={id + side} className={`bm-muscle ${on ? "on" : ""}`} onClick={() => onToggle(id)}
             role="button" aria-pressed={on} aria-label={labels[id] ?? id}>
            <title>{labels[id] ?? id}</title>
            {paths.map((d, i) => <path key={i} d={d} />)}
          </g>
        );
      })}
    </g>
  );
  return <g transform={`translate(${x} 0)`}>{half("l")}{half("r")}</g>;
}

export default function BodyMap({ selected, onToggle, labels }: Props) {
  return (
    <div className="bm-panel">
      <svg viewBox="10 0 400 400" className="bm-svg" role="group" aria-label="Tap sore muscles">
        <defs>
          <linearGradient id="bmBlue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#60a5fa" />
            <stop offset="100%" stopColor="#2563eb" />
          </linearGradient>
          <filter id="bmGlow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <Figure x={10} muscles={FRONT} selected={selected} onToggle={onToggle} labels={labels} />
        <Figure x={210} muscles={BACK} selected={selected} onToggle={onToggle} labels={labels} />
      </svg>
      <div className="bm-captions"><span>Front</span><span>Back</span></div>
    </div>
  );
}
