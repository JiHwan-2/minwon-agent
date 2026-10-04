// docs/submission/tech-sheet/기술설명서.md 의 표를 A4 세로 1페이지 Word 문서로 만든다 (별지 1 양식: 항목 | 기재 내용 2열 표)
// 사용: docx 패키지가 필요하다 (저장소 밖 아무 폴더에서 `npm install docx@9` 후 그 폴더에서 실행)
//   node make_docx.js <기술설명서.md> <AI민원길잡이_기술설명서.docx> 17      (마지막 값: 글자 크기, 반 포인트 단위. 17 = 8.5pt)
// PDF는 Word로 열어 '다른 이름으로 저장 → PDF'. 1페이지를 넘으면 문장을 줄인다 (표 항목은 지우지 않음).
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, VerticalAlign, BorderStyle, TableLayoutType,
} = require("docx");

const SRC = process.argv[2];
const OUT = process.argv[3];
const SIZE = Number(process.argv[4] || 17); // 반 포인트 단위 (17 = 8.5pt)
const FONT = "맑은 고딕";

const md = fs.readFileSync(SRC, "utf8");
const rows = md.split(/\r?\n/)
  .filter((l) => l.startsWith("| ") && !l.startsWith("| 항목") && !l.startsWith("|---"))
  .map((l) => l.slice(2, -2).split(" | "))
  .map(([label, ...rest]) => [label.trim(), rest.join(" | ").trim()]);

// **굵게**, `코드` 를 글자 조각으로
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, size: SIZE, ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), font: FONT, size: SIZE, bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: "Consolas", size: SIZE - 1, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, size: SIZE, ...base }));
  return out;
}

// 칸 안에서 줄을 나눌 곳: Workflow ①~⑦, 핵심기능 1)~5), Memory/Feedback, 기존자산/신규개발
function lines(label, text) {
  if (label.startsWith("핵심 Workflow")) return text.split(/ (?=[①②③④⑤⑥⑦])/);
  if (label.startsWith("핵심기능")) return [text];
  if (label.startsWith("Memory")) return text.split(/ · (?=\*\*Feedback)/);
  if (label.startsWith("기존자산")) return text.split(/ · (?=\*\*8일)/);
  if (label.startsWith("대표 테스트")) return text.split(/ (?=평가 세트:)/);
  return [text];
}

const TABLE_W = 11906 - 2 * 850; // A4 폭 - 좌우 여백 15mm
const LABEL_W = 2000;
const border = { style: BorderStyle.SINGLE, size: 4, color: "8EA6CF" };
const borders = { top: border, bottom: border, left: border, right: border };
const margins = { top: 28, bottom: 28, left: 80, right: 80 };

const table = new Table({
  width: { size: TABLE_W, type: WidthType.DXA },
  columnWidths: [LABEL_W, TABLE_W - LABEL_W],
  layout: TableLayoutType.FIXED,
  rows: [
    new TableRow({
      tableHeader: true,
      children: ["항목", "기재 내용"].map((h, i) => new TableCell({
        width: { size: i ? TABLE_W - LABEL_W : LABEL_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: "1D3F86", color: "auto" }, borders, margins,
        verticalAlign: VerticalAlign.CENTER,
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: runs(h, { bold: true, color: "FFFFFF" }) })],
      })),
    }),
    ...rows.map(([label, text]) => new TableRow({
      cantSplit: true,
      children: [
        new TableCell({
          width: { size: LABEL_W, type: WidthType.DXA }, borders, margins, verticalAlign: VerticalAlign.CENTER,
          shading: { type: ShadingType.CLEAR, fill: "E8EFFC", color: "auto" },
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: runs(label, { bold: true, color: "1D3F86" }) })],
        }),
        new TableCell({
          width: { size: TABLE_W - LABEL_W, type: WidthType.DXA }, borders, margins, verticalAlign: VerticalAlign.CENTER,
          children: lines(label, text).map((l) => new Paragraph({ spacing: { after: 0, line: 240 }, children: runs(l) })),
        }),
      ],
    })),
  ],
});

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: SIZE } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 850, bottom: 680, left: 850, right: 850 } } },
    children: [
      new Paragraph({ spacing: { after: 40 }, children: [
        new TextRun({ text: "<별지 1> ", font: FONT, size: 22, color: "55627A" }),
        new TextRun({ text: "AI Agent 기술설명서", font: FONT, size: 30, bold: true, color: "0B2559" }),
        new TextRun({ text: "   AI민원길잡이", font: FONT, size: 24, bold: true, color: "1D5BD6" }),
      ] }),
      new Paragraph({ spacing: { after: 100 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: "1D5BD6", space: 2 } },
        children: [new TextRun({ text: "제4회 경남 AI·SW 경진대회 2026 · 대학부 · 01 사회문제 해결형 AI Agent · 수치는 2026-10-04 실제 실행 기준",
          font: FONT, size: 16, color: "55627A" })] }),
      table,
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("저장:", OUT, rows.length + "행"); });
