// Run with: node tests/test_error_groups.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../nd30fmt/static/index.html'), 'utf8');
const start = source.indexOf('function canFixV(v,p=S.cur)');
const end = source.indexOf('function fixablePids()', start);
assert.ok(start > 0 && end > start);
const fixEnd = source.indexOf('async function fixParas(', end);
assert.ok(fixEnd > end);
const S = {cur: null};
const NOFIX_FIELDS = new Set(['position', 'page_start']);
const BULK_FIELDS = new Set(['font', 'color', 'size', 'bold', 'italic', 'underline', 'caps', 'align', 'indent', 'spacing', 'line_spacing', 'char_spacing']);
const keyOf = v => v.key || (v.target + '|' + v.field);
const group = new Function('S','NOFIX_FIELDS','BULK_FIELDS','keyOf', source.slice(start,end) + '\nreturn similarFixGroups;')(S,NOFIX_FIELDS,BULK_FIELDS,keyOf);
const fixable = new Function('S','NOFIX_FIELDS','keyOf', source.slice(start,source.indexOf('function similarFixGroups(',start)) + source.slice(end,fixEnd) + '\nreturn fixablePids;')(S,NOFIX_FIELDS,keyOf);

const v = (target,field,role='dang_body',extra={}) => ({target,field,role,scope:'paragraph',expected:'cỡ 14–15',source:'HD 05',severity:'loi',fixable:true,...extra});
const errors = [
  v('P1','size'),v('P2','size'),v('P3','size','dang_body',{ignored:true}),
  v('P4','size','body'),v('P5','size','body'),
  v('P6','size','dang_body',{expected:'cỡ 12'}),
  v('P7','position'),v('P8','position'),
  v('P9','bold','dang_dieu',{fixable:false}),v('P10','bold','dang_dieu',{fixable:false}),
];
const p = {
  violations_after:errors,
  _role:Object.fromEntries(errors.map(x=>[x.target,{role:x.role}])),
  _after:new Set(errors.filter(x=>x.target!=='P2').map(x=>x.target+'|'+x.field)),
  _rev:new Set(['P9','P10']),
};
S.cur=p;
assert.equal(group(p).length,2);
assert.deepEqual([...group(p).find(g=>g.field==='size').pids],['P4','P5']);
assert.deepEqual([...group(p).find(g=>g.field==='bold').pids],['P9','P10']);
assert.equal(group(p).find(g=>g.field==='bold').uncertain.size,2);
assert.equal(group(p,'ignored').length,0);
assert.equal(group(p,'warn').length,0);
assert.deepEqual(fixable(),['P1','P4','P5','P6','P9','P10']);
console.log('Error grouping: OK');
