const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('frontend/coverage.js','utf8'),ctx);
const fixture = {inventory:{status:'ready',checked_at:'2026-10-26',qa:{
  lok_sabha:{records:100,chunks:500,metadata_without_index:2,date_from:'2018-02-02',date_to:'2026-03-17'},
  rajya_sabha_hf:{records:5,years:{2025:5},retrieval:'semantic'},
  rajya_sabha_kaggle:{records:20,years:{2009:5,2017:15},retrieval:'keyword'}},
  debate_catalogues:{lok_sabha:{records:200,date_from:'2009-02-12',date_to:'2026-08-03'}}},
  debate_fulltext:{houses:{lok_sabha:{indexed:10,date_from:'2025-01-01',date_to:'2026-08-03'}}}};
assert(ctx.coverageLines(fixture,'lok_sabha','qa').join(' ').includes('100 questions'));
assert(!ctx.coverageLines(fixture,'lok_sabha','qa').join(' ').includes('Rajya Sabha'));
const rs = ctx.coverageLines(fixture,'rajya_sabha','qa').join(' ');
assert(rs.includes('2009, 2017, 2025') && rs.includes('keyword'));
const debates = ctx.coverageLines(fixture,'lok_sabha','debate').join(' ');
assert(debates.includes('200 catalogue entries') && debates.includes('10 have indexed speech text'));
assert(!debates.includes('100 questions'));
assert(ctx.coverageLines({},'both','all')[0].includes('unavailable'));
console.log('Coverage UI copy: 6 assertions passed');
