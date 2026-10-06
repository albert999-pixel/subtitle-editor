const assert = require('node:assert/strict');
const fs = require('node:fs');
const {lowercaseExcept, remapSelection} = require('../web/case-tools.js');
assert.equal(lowercaseExcept('Привет Иван из МОСКВЫ!', new Set([1, 3])), 'привет Иван из МОСКВЫ!');
assert.equal(lowercaseExcept('ЁЛКА  ИВАН\tNASA', new Set([1, 2])), 'ёлка  ИВАН\tNASA');
assert.equal(lowercaseExcept('Москва Москва', new Set([1])), 'москва Москва');
assert.equal(lowercaseExcept('ИМЯ', new Set()), 'имя');
assert.equal(lowercaseExcept('Имя ФАМИЛИЯ', new Set([0, 1])), 'Имя ФАМИЛИЯ');
assert.equal(lowercaseExcept('', new Set()), '');
assert.deepEqual([...remapSelection('Это Иван', 'Вот Это Иван', new Set([1]))], [2]);
assert.deepEqual([...remapSelection('Это Иван', 'Это Игорь', new Set([1]))], [1]);
assert.deepEqual([...remapSelection('Это Иван', 'Это', new Set([1]))], []);
const html = fs.readFileSync(require.resolve('../web/index.html'), 'utf8');
const editor = fs.readFileSync(require.resolve('../web/editor.js'), 'utf8');
new Function(editor);
for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(match[1]);
assert.ok(!html.includes('hlColorPicker'));
assert.ok(editor.includes('const lines = rows.map(r => ({ text: r.text }));'));
console.log('Case operations, selection remapping and inline script syntax: OK');
assert.equal((editor.match(/\/\/ Глобальный обработчик Cmd\+Z/g) || []).length, 1);

const ai = require('../web/ai-tools.js');
const proposal = {
  max_chars: 24,
  groups: ['Мы проверили', 'Иван', 'из Москвы.'], group_ends: [2, 3, 5],
  lines: ['Мы проверили Иван', 'из Москвы.'], ends: [3, 5],
  quality_warnings: [{index: 1, reason: 'проверить смысл'}],
  group_quality_warnings: [{index: 2, reason: 'проверить смысл'}],
};
const source = [{text: 'Мы проверили Иван из Москвы.', preservedCase: new Set([2, 4])}];
for (const kind of ['packed', 'groups']) {
  const result = ai.applyVariant(source, ai.variant(proposal, kind));
  assert.equal(result.map(row => row.text).join(' '), source[0].text);
  const selectedWords = result.flatMap(row => [...row.preservedCase].map(index => row.text.split(' ')[index]));
  assert.deepEqual(selectedWords, ['Иван', 'Москвы.']);
  assert.equal(result.filter(row => row.reviewReasons.length).length, 1);
  assert.equal(result.find(row => row.reviewReasons.length).text, kind === 'groups' ? 'Иван' : 'Мы проверили Иван');
}
const marked = ai.applyVariant(source, ai.variant(proposal, 'groups'));
const snapshot = marked.map(ai.cloneRow);
marked[1].text = 'Игорь';
marked[1].reviewReasons.push('ещё одна причина');
assert.equal(snapshot[1].text, 'Иван');
assert.deepEqual(snapshot[1].reviewReasons, ['проверить смысл']);
assert.deepEqual(ai.reviewReasons(snapshot[0], snapshot[1], snapshot[1]), ['проверить смысл']);
const regrouped = ai.applyVariant(snapshot, {lines: [source[0].text], ends: [5], notes: [[]]});
assert.deepEqual(regrouped[0].reviewReasons, ['проверить смысл']);
const overlong = ai.variant({...proposal, max_chars: 3}, 'groups');
assert.equal(overlong.notes.filter(notes => notes.length).length, 3);
console.log('AI variants, original words, preserved case and persistent review marks: OK');
