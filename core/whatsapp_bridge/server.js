/**
 * WhatsApp Protocol Bridge using @whiskeysockets/baileys
 * Provides a lightweight, high-performance background daemon connecting directly
 * to WhatsApp WebSockets without Chromium or headless browser overhead.
 */

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, Browsers } = require('@whiskeysockets/baileys');
const pino = require('pino');
const http = require('http');
const url = require('url');
const path = require('path');
const fs = require('fs');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');

const PORT = parseInt(process.env.WHATSAPP_BRIDGE_PORT || '48888', 10);
const DATA_DIR = path.resolve(__dirname, '../../data/whatsapp_baileys_auth');
const CACHE_FILE = path.join(DATA_DIR, 'store_cache.json');

// Ensure data folder exists
if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
}

// In-memory state
let sock = null;
let connectionState = 'INITIALIZING'; // INITIALIZING, QR_READY, CONNECTING, CONNECTED, DISCONNECTED, LOGGED_OUT
let currentQR = null;
let currentPairingCode = null;
let userInfo = null;
const eventQueue = [];
let recentMessages = {}; // jid -> Array of messages
let contacts = {}; // jid -> { name, notify, pushName, phone }
let unreadCounts = {}; // jid -> count
const BRIDGE_START_TIME = Date.now();
let bridgeReadyTimestamp = Date.now();

// Load persistent store cache if exists
try {
    if (fs.existsSync(CACHE_FILE)) {
        const raw = fs.readFileSync(CACHE_FILE, 'utf8');
        const parsed = JSON.parse(raw);
        contacts = parsed.contacts || {};
        recentMessages = parsed.recentMessages || {};
        // Do NOT load stale unread counts from previous days or sessions.
        // WhatsApp server sync upon connection is authoritative for true phone unread status.
        unreadCounts = {};
        // Auto-reconcile any LIDs to phone address book contacts
        for (const [jid, c] of Object.entries(contacts)) {
            if (jid.includes('@lid')) {
                const phone = getPhoneFromLid(jid);
                if (phone) {
                    const phoneJid = `${phone}@s.whatsapp.net`;
                    if (contacts[phoneJid] && contacts[phoneJid].name && !isEmailAddress(contacts[phoneJid].name)) {
                        contacts[jid] = {
                            ...contacts[jid],
                            name: contacts[phoneJid].name,
                            phone: phone
                        };
                    }
                }
            }
        }
    }
} catch (e) {
    // start fresh
}

function saveStoreCache() {
    try {
        const trimmedMessages = {};
        for (const [jid, msgs] of Object.entries(recentMessages)) {
            trimmedMessages[jid] = msgs.slice(-50);
        }
        fs.writeFileSync(CACHE_FILE, JSON.stringify({
            contacts,
            recentMessages: trimmedMessages,
            unreadCounts
        }, null, 2), 'utf8');
    } catch (e) {
        // silent cache write fail
    }
}

// Save cache every 15 seconds
setInterval(saveStoreCache, 15000);

// Helper to extract clean text and msg_type
function extractMessageInfo(msg) {
    const m = msg.message;
    if (!m) return { text: '', type: 'unknown' };

    if (m.conversation) {
        return { text: m.conversation, type: 'message' };
    }
    if (m.extendedTextMessage?.text) {
        return { text: m.extendedTextMessage.text, type: 'message' };
    }
    if (m.imageMessage) {
        const cap = m.imageMessage.caption ? `: ${m.imageMessage.caption}` : '';
        return { text: `[Photo${cap}]`, type: 'photo' };
    }
    if (m.videoMessage) {
        const cap = m.videoMessage.caption ? `: ${m.videoMessage.caption}` : '';
        return { text: `[Video${cap}]`, type: 'video' };
    }
    if (m.audioMessage) {
        return { text: '[Voice Note]', type: 'voice note' };
    }
    if (m.documentMessage) {
        const fname = m.documentMessage.fileName || m.documentMessage.caption || '';
        return { text: fname ? `[Document: ${fname}]` : '[Document]', type: 'document' };
    }
    if (m.stickerMessage) {
        return { text: '[Sticker]', type: 'sticker' };
    }
    if (m.contactMessage) {
        return { text: `[Contact: ${m.contactMessage.displayName || ''}]`, type: 'contact' };
    }
    if (m.locationMessage) {
        return { text: '[Location]', type: 'location' };
    }
    return { text: '', type: 'message' };
}

function isEmailAddress(str) {
    if (!str || typeof str !== 'string') return false;
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str.trim());
}

// In-memory cache for fast reverse LID -> phone resolution
const lidToPhoneCache = {};

function getPhoneFromLid(jid) {
    if (!jid || !jid.includes('@lid')) return null;
    const lidUser = jid.split('@')[0];
    if (lidToPhoneCache[lidUser]) return lidToPhoneCache[lidUser];

    const reverseFile = path.join(DATA_DIR, `lid-mapping-${lidUser}_reverse.json`);
    try {
        if (fs.existsSync(reverseFile)) {
            const raw = fs.readFileSync(reverseFile, 'utf8');
            const phone = JSON.parse(raw);
            if (phone) {
                lidToPhoneCache[lidUser] = String(phone);
                return String(phone);
            }
        }
    } catch (e) {}

    return null;
}

function getContactInfo(jid) {
    if (!jid) return null;
    // 1. Direct check in contacts
    if (contacts[jid]) return contacts[jid];

    // 2. If LID, resolve to phone number
    if (jid.includes('@lid')) {
        const phone = getPhoneFromLid(jid);
        if (phone) {
            const phoneJid = `${phone}@s.whatsapp.net`;
            if (contacts[phoneJid]) return contacts[phoneJid];
        }
    }

    // 3. If phone JID, check phone@s.whatsapp.net
    if (jid.includes('@')) {
        const phone = jid.split('@')[0];
        const phoneJid = `${phone}@s.whatsapp.net`;
        if (contacts[phoneJid]) return contacts[phoneJid];
    }

    return null;
}

// Resolve contact name from jid - strictly prioritizes YOUR saved phone contacts
function getContactName(jid) {
    if (!jid) return 'Unknown';

    // 1. If LID, resolve to Phone JID FIRST because address book contacts are saved under phone JID!
    if (jid.includes('@lid')) {
        const phone = getPhoneFromLid(jid);
        if (phone) {
            const phoneJid = `${phone}@s.whatsapp.net`;
            const pc = contacts[phoneJid];
            if (pc && pc.name && pc.name.trim() && !isEmailAddress(pc.name)) {
                return pc.name.trim();
            }
        }
    }

    const c = getContactInfo(jid);

    // 2. Highest priority: The exact name YOU saved in your phone address book!
    if (c && c.name && c.name.trim()) {
        const savedName = c.name.trim();
        if (!isEmailAddress(savedName)) {
            return savedName;
        }
    }

    // 3. Verified business name
    if (c && c.verifiedName && c.verifiedName.trim()) {
        return c.verifiedName.trim();
    }

    // 3. Check if LID resolves to a phone and that phone has a saved name
    if (jid.includes('@lid')) {
        const phone = getPhoneFromLid(jid);
        if (phone) {
            const pc = contacts[`${phone}@s.whatsapp.net`];
            if (pc && pc.name && !isEmailAddress(pc.name)) {
                return pc.name;
            }
        }
    }

    // 4. Sender's WhatsApp nickname (notify) if not an email
    if (c && c.notify && c.notify.trim() && !isEmailAddress(c.notify)) {
        return c.notify.trim();
    }

    // 5. WhatsApp profile pushName if not an email
    if (c && c.pushName && c.pushName.trim() && !isEmailAddress(c.pushName)) {
        return c.pushName.trim();
    }

    // 6. Clean phone number rather than an email or weird handle
    const phone = jid.includes('@lid') ? getPhoneFromLid(jid) : jid.split('@')[0].replace(/[^0-9]/g, '');
    if (phone && phone.length >= 7) {
        return `+${phone}`;
    }

    return c?.name || c?.notify || c?.pushName || 'Someone';
}

function getRecentMessagesForJid(jid) {
    let list = recentMessages[jid] ? [...recentMessages[jid]] : [];
    if (jid.includes('@s.whatsapp.net')) {
        const phone = jid.split('@')[0];
        for (const [otherJid, msgs] of Object.entries(recentMessages)) {
            if (otherJid.includes('@lid')) {
                const mappedPhone = getPhoneFromLid(otherJid);
                if (mappedPhone === phone && msgs) {
                    list = list.concat(msgs);
                }
            }
        }
    } else if (jid.includes('@lid')) {
        const phone = getPhoneFromLid(jid);
        if (phone && recentMessages[`${phone}@s.whatsapp.net`]) {
            list = list.concat(recentMessages[`${phone}@s.whatsapp.net`]);
        }
    }

    const resolvedName = getContactName(jid);
    const seen = new Set();
    const deduped = [];
    for (const m of list) {
        if (!m.id || !seen.has(m.id)) {
            if (m.id) seen.add(m.id);
            deduped.push({
                ...m,
                sender: m.fromMe ? 'You' : resolvedName
            });
        }
    }
    deduped.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    return deduped;
}

function clearUnreadForJid(jid) {
    unreadCounts[jid] = 0;
    if (jid.includes('@s.whatsapp.net')) {
        const phone = jid.split('@')[0];
        for (const otherJid of Object.keys(unreadCounts)) {
            if (otherJid.includes('@lid')) {
                const mappedPhone = getPhoneFromLid(otherJid);
                if (mappedPhone === phone) {
                    unreadCounts[otherJid] = 0;
                }
            }
        }
    } else if (jid.includes('@lid')) {
        const phone = getPhoneFromLid(jid);
        if (phone) {
            unreadCounts[`${phone}@s.whatsapp.net`] = 0;
        }
    }
}

// --- Fuzzy Contact Search & Matching ---
function normalizeName(str) {
    if (!str || typeof str !== 'string') return '';
    return str
        .toLowerCase()
        .replace(/[\p{Extended_Pictographic}\u{1F300}-\u{1F9FF}]/gu, '')
        .replace(/[^\w\s]/g, '')
        .replace(/(.)\1+/g, '$1')
        .trim();
}

function levenshteinDistance(s1, s2) {
    if (!s1 || !s2) return (s1 || s2).length;
    const m = s1.length;
    const n = s2.length;
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 0; i <= m; i++) dp[i][0] = i;
    for (let j = 0; j <= n; j++) dp[0][j] = j;
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (s1[i - 1] === s2[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1];
            } else {
                dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
            }
        }
    }
    return dp[m][n];
}

function fuzzyMatchScore(candidate, query) {
    if (!candidate || !query) return 0;
    const cLow = candidate.toLowerCase().trim();
    const qLow = query.toLowerCase().trim();

    // 1. Exact raw match
    if (cLow === qLow) return 100;

    // 2. Starts with query (e.g. "Praveen" in "Praveen Patil Sir")
    if (cLow.startsWith(qLow)) return 95;
    if (cLow.includes(qLow)) return 90;

    // 3. Word token match (e.g. "Sir" in "Professor Sir")
    const words = cLow.split(/\s+/);
    if (words.some(w => w === qLow || w.startsWith(qLow))) return 88;

    // 4. Normalized match (collapsing repeated letters e.g. "aishuuu" <-> "aishu" & stripping emojis)
    const normC = normalizeName(candidate);
    const normQ = normalizeName(query);
    if (normC === normQ) return 96;
    if (normC.startsWith(normQ) || normC.includes(normQ) || normQ.includes(normC)) return 85;

    // 5. Normalized word token match
    const normWords = normC.split(/\s+/);
    if (normWords.some(w => w === normQ || w.startsWith(normQ) || normQ.startsWith(w))) return 80;

    // 6. Levenshtein edit distance on normalized name
    const maxLen = Math.max(normC.length, normQ.length);
    if (maxLen >= 3) {
        const dist = levenshteinDistance(normC, normQ);
        if (dist <= 2) {
            return 75 - dist * 10;
        }
    }

    return 0;
}

function searchContacts(query, limit = 10) {
    if (!query || !query.trim()) return [];
    const q = query.trim();
    const results = [];
    const seenPhones = new Set();

    for (const [jid, info] of Object.entries(contacts)) {
        const contactName = getContactName(jid);
        if (!contactName || isEmailAddress(contactName)) continue;
        const phone = jid.includes('@lid') ? getPhoneFromLid(jid) : jid.split('@')[0].replace(/[^0-9]/g, '');
        if (phone && seenPhones.has(phone)) continue;

        let maxScore = fuzzyMatchScore(contactName, q);
        if (info.phone && q.replace(/[^0-9]/g, '').length >= 4 && info.phone.includes(q.replace(/[^0-9]/g, ''))) {
            maxScore = Math.max(maxScore, 90);
        }

        if (maxScore >= 60) {
            if (phone) seenPhones.add(phone);
            results.push({
                name: contactName,
                phone: phone ? `+${phone}` : '',
                jid: jid,
                score: maxScore
            });
        }
    }

    results.sort((a, b) => b.score - a.score);
    return results.slice(0, limit);
}

function getAllSavedContacts(limit = 100) {
    const list = [];
    const seen = new Set();
    for (const [jid, info] of Object.entries(contacts)) {
        const name = getContactName(jid);
        const phone = jid.includes('@lid') ? getPhoneFromLid(jid) : jid.split('@')[0].replace(/[^0-9]/g, '');
        if (!name || isEmailAddress(name) || name.startsWith('+')) continue;
        if (seen.has(name.toLowerCase())) continue;
        seen.add(name.toLowerCase());
        list.push({
            name: name,
            phone: phone ? `+${phone}` : '',
            jid: jid
        });
    }
    list.sort((a, b) => a.name.localeCompare(b.name));
    return list.slice(0, limit);
}

// Resolve JID from user input (contact name or phone number)
function resolveJid(target) {
    if (!target) return null;
    let clean = target.trim();

    // Already a JID
    if (clean.includes('@s.whatsapp.net') || clean.includes('@g.us')) {
        return clean;
    }

    // Phone number: digits only (length >= 7)
    let digitsOnly = clean.replace(/[^0-9]/g, '');
    if (digitsOnly.length === 10 && /^[6-9]/.test(digitsOnly)) {
        // Automatically prepend standard country code (+91) for 10-digit mobile numbers
        digitsOnly = '91' + digitsOnly;
    }
    if (digitsOnly.length >= 7 && (clean.startsWith('+') || /^\d+$/.test(clean))) {
        return `${digitsOnly}@s.whatsapp.net`;
    }

    // 1. Fuzzy search in contacts
    const matches = searchContacts(clean, 1);
    if (matches && matches.length > 0 && matches[0].score >= 60) {
        return matches[0].jid;
    }

    // 2. Check recentMessages keys
    const lowTarget = clean.toLowerCase();
    for (const jid of Object.keys(recentMessages)) {
        const cName = getContactName(jid).toLowerCase();
        if (cName === lowTarget || cName.includes(lowTarget) || fuzzyMatchScore(cName, clean) >= 60) {
            return jid;
        }
    }

    // Fallback: If digits exist, use them
    if (digitsOnly.length >= 7) {
        return `${digitsOnly}@s.whatsapp.net`;
    }

    return null;
}

async function startBridge() {
    connectionState = 'CONNECTING';
    const { state, saveCreds } = await useMultiFileAuthState(DATA_DIR);
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        browser: Browsers.windows('Desktop'),
        syncFullHistory: false,
        generateHighQualityLinkPreview: false,
        markOnlineOnConnect: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQR = qr;
            connectionState = 'QR_READY';
            console.log('[WhatsApp Bridge] 📱 New QR code generated.');
            try {
                fs.writeFileSync(path.join(DATA_DIR, 'last_qr.txt'), qr, 'utf8');
            } catch (e) {}
            // Also print QR to terminal if in foreground
            try {
                qrcodeTerminal.generate(qr, { small: true });
            } catch (e) {}
        }

        if (connection === 'close') {
            currentQR = null;
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`[WhatsApp Bridge] ⚠️ Connection closed (status: ${statusCode}). Reconnect: ${shouldReconnect}`);

            if (shouldReconnect) {
                connectionState = 'CONNECTING';
                setTimeout(startBridge, 3000);
            } else {
                connectionState = 'LOGGED_OUT';
                console.log('[WhatsApp Bridge] 🚪 Session logged out. Please re-pair.');
            }
        } else if (connection === 'open') {
            connectionState = 'CONNECTED';
            currentQR = null;
            userInfo = sock.user;
            bridgeReadyTimestamp = Date.now();
            console.log(`[WhatsApp Bridge] ✅ Connected successfully! Logged in as: ${sock.user?.id || 'Unknown'}`);
        }
    });

    // Full history sync from phone
    sock.ev.on('messaging-history.set', ({ contacts: newContacts, chats: newChats }) => {
        if (newContacts && Array.isArray(newContacts)) {
            for (const c of newContacts) {
                if (!c.id) continue;
                const entry = {
                    name: c.name || contacts[c.id]?.name,
                    notify: c.notify || contacts[c.id]?.notify,
                    verifiedName: c.verifiedName || contacts[c.id]?.verifiedName,
                    pushName: c.pushName,
                    phone: c.id.split('@')[0]
                };
                contacts[c.id] = { ...contacts[c.id], ...entry };
                if (c.lid) {
                    contacts[c.lid] = { ...contacts[c.lid], ...entry };
                }
            }
        }
        if (newChats && Array.isArray(newChats)) {
            for (const chat of newChats) {
                if (!chat.id) continue;
                if (chat.name && (!contacts[chat.id] || !contacts[chat.id].name)) {
                    contacts[chat.id] = {
                        ...contacts[chat.id],
                        name: chat.name
                    };
                }
                // Sync true unread status from WhatsApp phone state
                if (typeof chat.unreadCount === 'number') {
                    unreadCounts[chat.id] = Math.max(0, chat.unreadCount);
                } else {
                    unreadCounts[chat.id] = 0;
                }
            }
        }
        saveStoreCache();
    });

    // Contacts tracking
    sock.ev.on('contacts.upsert', (newContacts) => {
        for (const c of newContacts) {
            if (!c.id) continue;
            const entry = {
                name: c.name || contacts[c.id]?.name,
                notify: c.notify || contacts[c.id]?.notify,
                verifiedName: c.verifiedName || contacts[c.id]?.verifiedName,
                pushName: c.pushName,
                phone: c.id.split('@')[0]
            };
            contacts[c.id] = { ...contacts[c.id], ...entry };
            if (c.lid) {
                contacts[c.lid] = { ...contacts[c.lid], ...entry };
            }
        }
        saveStoreCache();
    });

    sock.ev.on('contacts.update', (updates) => {
        for (const u of updates) {
            if (!u.id) continue;
            contacts[u.id] = {
                ...contacts[u.id],
                ...u
            };
        }
        saveStoreCache();
    });

    // Chats upsert & update (tracks real-time unread changes from phone)
    sock.ev.on('chats.upsert', (newChats) => {
        for (const chat of newChats) {
            if (!chat.id) continue;
            if (chat.name && (!contacts[chat.id] || !contacts[chat.id].name)) {
                contacts[chat.id] = {
                    ...contacts[chat.id],
                    name: chat.name
                };
            }
            if (typeof chat.unreadCount === 'number') {
                unreadCounts[chat.id] = Math.max(0, chat.unreadCount);
            }
        }
        saveStoreCache();
    });

    sock.ev.on('chats.update', (updates) => {
        for (const u of updates) {
            if (!u.id) continue;
            if (typeof u.unreadCount === 'number') {
                unreadCounts[u.id] = Math.max(0, u.unreadCount);
                if (u.unreadCount === 0) {
                    clearUnreadForJid(u.id);
                }
            }
            if (u.read === true) {
                clearUnreadForJid(u.id);
            }
        }
        saveStoreCache();
    });

    // Message read receipts & status updates (when messages are read on phone)
    sock.ev.on('messages.update', (updates) => {
        for (const u of updates) {
            const jid = u.key?.remoteJid;
            if (!jid) continue;
            if (u.update?.status === 4 || u.update?.status === 3 || u.update?.read === true) {
                const msgs = recentMessages[jid] || [];
                const last = msgs[msgs.length - 1];
                if (last && last.id === u.key?.id) {
                    clearUnreadForJid(jid);
                } else if (unreadCounts[jid] > 0) {
                    unreadCounts[jid] = Math.max(0, unreadCounts[jid] - 1);
                }
            }
        }
    });

    sock.ev.on('message-receipt.update', (receipts) => {
        for (const r of receipts) {
            if (r.receipt?.userJid || r.receipt?.readTimestamp) {
                const jid = r.key?.remoteJid;
                if (jid) {
                    clearUnreadForJid(jid);
                }
            }
        }
    });

    // Inbound & Outbound messages tracking
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        for (const msg of messages) {
            if (!msg.message) continue;
            const jid = msg.key.remoteJid;
            if (!jid || jid.endsWith('@broadcast') || jid === 'status@broadcast') continue;

            const fromMe = Boolean(msg.key.fromMe);
            const incoming = !fromMe;
            const { text, type: msgType } = extractMessageInfo(msg);
            if (!text && msgType === 'unknown') continue;

            // If message came from LID, link it to the phone contact right away!
            if (jid.includes('@lid')) {
                const mappedPhone = getPhoneFromLid(jid);
                if (mappedPhone) {
                    const phoneJid = `${mappedPhone}@s.whatsapp.net`;
                    if (contacts[phoneJid]) {
                        contacts[jid] = {
                            ...contacts[phoneJid],
                            lid: jid
                        };
                    }
                }
            }

            // Update contact push name if available without overwriting saved contact name
            if (msg.pushName) {
                if (!contacts[jid]) contacts[jid] = {};
                contacts[jid].pushName = msg.pushName;
                if (!contacts[jid].name && !isEmailAddress(msg.pushName)) {
                    contacts[jid].name = msg.pushName;
                }
            }

            const messageEntry = {
                id: msg.key.id,
                fromMe: fromMe,
                incoming: incoming,
                text: text,
                msg_type: msgType,
                timestamp: msg.messageTimestamp ? Number(msg.messageTimestamp) * 1000 : Date.now(),
                sender: fromMe ? 'You' : getContactName(jid)
            };

            if (!recentMessages[jid]) recentMessages[jid] = [];
            recentMessages[jid].push(messageEntry);
            if (recentMessages[jid].length > 50) {
                recentMessages[jid].shift();
            }

            // Distinguish fresh, real-time live incoming messages from historical catch-up messages.
            // Messages sent overnight or while the PC was off must NEVER trigger voice alerts or fake unread counts.
            const isLive = incoming &&
                           type === 'notify' &&
                           messageEntry.timestamp >= (bridgeReadyTimestamp - 15000) &&
                           connectionState === 'CONNECTED';

            if (incoming) {
                if (isLive) {
                    unreadCounts[jid] = (unreadCounts[jid] || 0) + 1;
                    const contactName = getContactName(jid);
                    console.log(`[WhatsApp Bridge] 📩 Live incoming from ${contactName}: "${text.slice(0, 50)}"`);

                    // Proactive voice alerts are strictly for direct 1-on-1 chats (or if mentioned in groups)
                    const isGroup = jid.endsWith('@g.us');
                    const myJid = userInfo?.id?.split(':')[0]?.split('@')[0];
                    const mentionedMe = isGroup && msg.message?.extendedTextMessage?.contextInfo?.mentionedJid?.some(m => m.includes(myJid));

                    if (!isGroup || mentionedMe) {
                        eventQueue.push({
                            event: 'new_message',
                            contact: contactName,
                            jid: jid,
                            text: text,
                            msg_type: msgType,
                            timestamp: messageEntry.timestamp
                        });
                    }
                } else {
                    // Stored in recentMessages for history, but ignored for proactive voice alerts
                    console.log(`[WhatsApp Bridge] 📜 Synced historical message from ${getContactName(jid)} (${new Date(messageEntry.timestamp).toLocaleTimeString()}) - Ignored for proactive voice alert`);
                }
            } else {
                // If we replied (either from PC or from phone), reset unread count
                clearUnreadForJid(jid);
            }
        }
    });
}

// --- HTTP API ---
const server = http.createServer(async (req, res) => {
    const parsed = new URL(req.url, `http://${req.headers.host || '127.0.0.1'}`);
    const pathname = parsed.pathname;
    const method = req.method;

    res.setHeader('Content-Type', 'application/json');

    // CORS headers for local tools
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (method === 'OPTIONS') {
        res.writeHead(200);
        return res.end();
    }

    try {
        // 1. Status
        if (pathname === '/status' && method === 'GET') {
            res.writeHead(200);
            return res.end(JSON.stringify({
                status: connectionState,
                authenticated: connectionState === 'CONNECTED',
                user: userInfo,
                has_qr: Boolean(currentQR),
                pairing_code: currentPairingCode
            }));
        }

        // 2. Events polling (drain queue)
        if (pathname === '/events' && method === 'GET') {
            const events = eventQueue.splice(0, eventQueue.length);
            res.writeHead(200);
            return res.end(JSON.stringify({ events }));
        }

        // 3. Web QR code viewer (HTML page for easy phone scanning)
        if (pathname === '/qr' && method === 'GET') {
            res.setHeader('Content-Type', 'text/html');
            if (connectionState === 'CONNECTED') {
                res.writeHead(200);
                return res.end(`
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>S.P.I.D.Y. WhatsApp Pairing</title>
                        <style>body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding: 50px; background: #0b0f19; color: #10b981; }</style>
                    </head>
                    <body>
                        <h1>✅ WhatsApp is Connected!</h1>
                        <p style="color: #94a3b8;">S.P.I.D.Y. is linked and authenticated. You can close this window now.</p>
                    </body>
                    </html>
                `);
            }

            if (!currentQR) {
                res.writeHead(200);
                return res.end(`
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>S.P.I.D.Y. WhatsApp Pairing</title>
                        <meta http-equiv="refresh" content="3">
                        <style>body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding: 50px; background: #0b0f19; color: #e2e8f0; }</style>
                    </head>
                    <body>
                        <h2>🔄 Generating WhatsApp QR Code...</h2>
                        <p style="color: #94a3b8;">This page will auto-refresh in 3 seconds.</p>
                    </body>
                    </html>
                `);
            }

            try {
                const qrImageDataUrl = await QRCode.toDataURL(currentQR, {
                    width: 320,
                    margin: 2,
                    color: {
                        dark: '#000000',
                        light: '#ffffff'
                    }
                });

                const html = `
                <!DOCTYPE html>
                <html>
                <head>
                    <title>S.P.I.D.Y. WhatsApp Pairing</title>
                    <meta http-equiv="refresh" content="20">
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                            text-align: center;
                            padding: 40px 20px;
                            background: #0f172a;
                            color: #f8fafc;
                        }
                        .card {
                            max-width: 440px;
                            margin: 0 auto;
                            background: #1e293b;
                            padding: 30px;
                            border-radius: 16px;
                            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                            border: 1px solid #334155;
                        }
                        h1 { font-size: 22px; margin-bottom: 8px; color: #38bdf8; }
                        p { color: #94a3b8; font-size: 14px; margin-bottom: 20px; }
                        .qr-box {
                            background: #ffffff;
                            padding: 16px;
                            display: inline-block;
                            border-radius: 12px;
                            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                        }
                        .steps {
                            text-align: left;
                            margin-top: 24px;
                            font-size: 14px;
                            line-height: 1.6;
                            color: #cbd5e1;
                            background: #0f172a;
                            padding: 16px 20px;
                            border-radius: 8px;
                        }
                        .badge {
                            display: inline-block;
                            margin-top: 15px;
                            font-size: 12px;
                            color: #64748b;
                        }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>S.P.I.D.Y. WhatsApp Pairing</h1>
                        <p>Scan the QR code below using WhatsApp on your phone:</p>
                        <div class="qr-box">
                            <img src="${qrImageDataUrl}" alt="WhatsApp QR Code" width="300" height="300" />
                        </div>
                        <div class="steps">
                            <strong>How to connect:</strong><br>
                            1. Open <strong>WhatsApp</strong> on your phone.<br>
                            2. Tap <strong>Settings</strong> (iOS) or <strong>⋮ Menu</strong> (Android).<br>
                            3. Tap <strong>Linked Devices</strong> &rarr; <strong>Link a Device</strong>.<br>
                            4. Point your camera at this QR code.
                        </div>
                        <div class="badge">🔄 Auto-refreshes every 20 seconds</div>
                    </div>
                </body>
                </html>
                `;
                res.writeHead(200);
                return res.end(html);
            } catch (qrErr) {
                res.writeHead(500);
                return res.end('<h3>Error rendering QR code: ' + qrErr.message + '</h3>');
            }
        }

        // 4. Request Phone Pairing Code
        if (pathname === '/pair_phone' && method === 'POST') {
            let body = '';
            req.on('data', chunk => { body += chunk; });
            req.on('end', async () => {
                try {
                    const data = JSON.parse(body || '{}');
                    const phone = (data.phone || '').replace(/[^0-9]/g, '');
                    if (!phone || phone.length < 7) {
                        res.writeHead(400);
                        return res.end(JSON.stringify({ success: false, error: 'Valid phone number required' }));
                    }
                    if (!sock || connectionState === 'CONNECTED') {
                        res.writeHead(400);
                        return res.end(JSON.stringify({ success: false, error: 'Socket not ready or already connected' }));
                    }
                    const code = await sock.requestPairingCode(phone);
                    currentPairingCode = code;
                    res.writeHead(200);
                    return res.end(JSON.stringify({ success: true, code: code }));
                } catch (e) {
                    res.writeHead(500);
                    return res.end(JSON.stringify({ success: false, error: e.message }));
                }
            });
            return;
        }

        // 5. Unread Senders
        if (pathname === '/unread' && method === 'GET') {
            const directOnly = parsed.searchParams.get('direct_only') === 'true';
            const list = [];
            const seenSenders = new Set();
            for (const [jid, count] of Object.entries(unreadCounts)) {
                if (count > 0) {
                    const isGroup = jid.endsWith('@g.us');
                    if (directOnly && isGroup) {
                        continue;
                    }
                    const msgs = recentMessages[jid] || [];
                    const last = msgs[msgs.length - 1];
                    // If the last message was sent by the user, this chat is NOT unread
                    if (last && last.fromMe) {
                        clearUnreadForJid(jid);
                        continue;
                    }
                    const contactName = getContactName(jid);
                    const phone = jid.includes('@lid') ? getPhoneFromLid(jid) : jid.split('@')[0].replace(/[^0-9]/g, '');
                    const dedupKey = phone || contactName;
                    if (seenSenders.has(dedupKey)) continue;
                    seenSenders.add(dedupKey);

                    list.push({
                        contact: contactName,
                        jid: jid,
                        is_group: isGroup,
                        count: count,
                        last_message: last ? last.text : ''
                    });
                }
            }
            res.writeHead(200);
            return res.end(JSON.stringify({ unread: list }));
        }

        // 5b. Search Contacts Endpoint
        if (pathname === '/search_contacts' && method === 'GET') {
            const q = parsed.searchParams.get('query') || '';
            const limit = parseInt(parsed.searchParams.get('limit') || '10', 10);
            const results = searchContacts(q, limit);
            res.writeHead(200);
            return res.end(JSON.stringify({
                success: true,
                count: results.length,
                contacts: results
            }));
        }

        // 5c. List All Saved Contacts Endpoint
        if (pathname === '/contacts' && method === 'GET') {
            const limit = parseInt(parsed.searchParams.get('limit') || '100', 10);
            const list = getAllSavedContacts(limit);
            res.writeHead(200);
            return res.end(JSON.stringify({
                success: true,
                count: list.length,
                contacts: list
            }));
        }

        // 6. Read Chat
        if ((pathname === '/chat' && method === 'GET') || (pathname === '/read_chat' && method === 'POST')) {
            let targetContact = parsed.searchParams.get('contact') || '';
            let limit = parseInt(parsed.searchParams.get('limit') || '10', 10);

            const handleRead = (contactQuery, maxMsgs) => {
                const jid = resolveJid(contactQuery);
                if (!jid) {
                    res.writeHead(404);
                    return res.end(JSON.stringify({
                        success: false,
                        error: `Contact '${contactQuery}' not found in contacts or recent conversations.`
                    }));
                }

                // Clear unread count for this chat and any linked LID/phone
                clearUnreadForJid(jid);

                const msgs = getRecentMessagesForJid(jid);
                const sliced = msgs.slice(-maxMsgs);

                // Send read receipt so phone clears unread badge as well
                if (sock && msgs.length > 0) {
                    const last = msgs[msgs.length - 1];
                    if (last && last.id && !last.fromMe) {
                        try {
                            sock.readMessages([{ remoteJid: jid, id: last.id, fromMe: false }]);
                        } catch (e) {}
                    }
                }

                res.writeHead(200);
                return res.end(JSON.stringify({
                    success: true,
                    contact: getContactName(jid),
                    jid: jid,
                    messages: sliced
                }));
            };

            if (method === 'POST') {
                let body = '';
                req.on('data', chunk => { body += chunk; });
                req.on('end', () => {
                    try {
                        const data = JSON.parse(body || '{}');
                        handleRead(data.contact || targetContact, parseInt(data.max_messages || limit, 10));
                    } catch (e) {
                        res.writeHead(400);
                        res.end(JSON.stringify({ success: false, error: 'Invalid JSON' }));
                    }
                });
                return;
            } else {
                return handleRead(targetContact, limit);
            }
        }

        // 7. Send Message
        if (pathname === '/send' && method === 'POST') {
            let body = '';
            req.on('data', chunk => { body += chunk; });
            req.on('end', async () => {
                try {
                    const data = JSON.parse(body || '{}');
                    const target = data.contact || data.recipient || '';
                    const message = data.message || data.text || '';

                    if (!target || !message) {
                        res.writeHead(400);
                        return res.end(JSON.stringify({ success: false, error: 'Missing contact or message' }));
                    }

                    if (connectionState !== 'CONNECTED' || !sock) {
                        res.writeHead(503);
                        return res.end(JSON.stringify({ success: false, error: 'WhatsApp is not connected. Please pair first.' }));
                    }

                    const jid = resolveJid(target);
                    if (!jid) {
                        res.writeHead(404);
                        return res.end(JSON.stringify({ success: false, error: `Could not find phone number or contact matching '${target}'` }));
                    }

                    console.log(`[WhatsApp Bridge] 📤 Sending message to ${jid} (${getContactName(jid)}): "${message.slice(0, 40)}"`);
                    const sent = await sock.sendMessage(jid, { text: message });

                    // Add to local recent messages
                    if (!recentMessages[jid]) recentMessages[jid] = [];
                    recentMessages[jid].push({
                        id: sent.key.id,
                        fromMe: true,
                        incoming: false,
                        text: message,
                        msg_type: 'message',
                        timestamp: Date.now(),
                        sender: 'You'
                    });

                    res.writeHead(200);
                    return res.end(JSON.stringify({
                        success: true,
                        contact: getContactName(jid),
                        jid: jid,
                        messageId: sent.key.id
                    }));
                } catch (e) {
                    console.error('[WhatsApp Bridge] ❌ Send error:', e);
                    res.writeHead(500);
                    return res.end(JSON.stringify({ success: false, error: e.message }));
                }
            });
            return;
        }

        // Default 404
        res.writeHead(404);
        return res.end(JSON.stringify({ error: 'Endpoint not found' }));

    } catch (err) {
        res.writeHead(500);
        return res.end(JSON.stringify({ error: err.message }));
    }
});

server.listen(PORT, '127.0.0.1', () => {
    console.log(`[WhatsApp Bridge] 🚀 Server running on http://127.0.0.1:${PORT}`);
    startBridge();
});
