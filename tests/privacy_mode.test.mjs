import assert from 'node:assert/strict';
import { isPrivacyShortcut } from '../web/privacy.js';

assert.equal(isPrivacyShortcut({ ctrlKey: true, key: 'b' }), true);
assert.equal(isPrivacyShortcut({ metaKey: true, key: 'B' }), true);
assert.equal(isPrivacyShortcut({ ctrlKey: false, metaKey: false, key: 'b' }), false);
assert.equal(isPrivacyShortcut({ ctrlKey: true, key: 'x' }), false);
