// TON Address utilities
// Converts raw TON addresses to user-friendly format WITHOUT @ton/core (browser-safe)

/**
 * Extract the canonical 64-hex hash-part of any TON address representation.
 *
 * TonConnect returns addresses in raw form ("0:abc...64hex"), while the backend
 * usually stores them in user-friendly base64url form ("UQ..." / "EQ..."). They
 * encode the SAME account but a naive string compare fails. This helper returns
 * the lowercase 64-char hex hash so that two formats can be compared safely.
 *
 * @param {string} address - any TON address (raw, user-friendly, with or without workchain prefix)
 * @returns {string|null} lowercase 64-char hex, or null if parsing failed
 */
export function getAddressHash(address) {
  if (!address || typeof address !== 'string') return null;
  const s = address.trim();

  // Raw form: "0:hex..." or "-1:hex..."
  if (s.includes(':')) {
    const hex = s.split(':')[1] || '';
    return /^[0-9a-fA-F]{64}$/.test(hex) ? hex.toLowerCase() : null;
  }

  // User-friendly form: 48 base64url chars (UQ.../EQ.../kQ.../0Q...)
  // 36 bytes total: 1 flag + 1 workchain + 32 hash + 2 crc → take bytes [2..34]
  if (/^[A-Za-z0-9_\-+/=]{46,48}$/.test(s)) {
    try {
      const std = s.replace(/-/g, '+').replace(/_/g, '/');
      const padded = std + '='.repeat((4 - (std.length % 4)) % 4);
      const bin = atob(padded);
      if (bin.length < 34) return null;
      let hex = '';
      for (let i = 2; i < 34; i++) {
        hex += bin.charCodeAt(i).toString(16).padStart(2, '0');
      }
      return hex;
    } catch (_) {
      return null;
    }
  }

  return null;
}

/**
 * Whether two TON addresses point to the same account, regardless of format
 * (raw vs user-friendly, bounceable vs non-bounceable, base64 vs base64url).
 * Falls back to a lowercase suffix compare if either address can't be parsed,
 * so we don't false-positive on legacy data.
 */
export function isSameTonAddress(a, b) {
  if (!a || !b) return false;
  const ha = getAddressHash(a);
  const hb = getAddressHash(b);
  if (ha && hb) return ha === hb;
  // graceful fallback: case-insensitive suffix compare
  const sa = a.toLowerCase().replace(/^0:/, '');
  const sb = b.toLowerCase().replace(/^0:/, '');
  return sa.slice(-40) === sb.slice(-40);
}

/**
 * Convert raw address (0:abc...) to user-friendly format (UQ.../EQ...)
 * Uses base64url encoding for browser compatibility
 * @param {string} rawAddress - Raw TON address starting with 0: or -1:
 * @param {Object} options - Options { testnet, bounceable }
 * @returns {string} User-friendly address
 */
export function toUserFriendlyAddress(rawAddress, options = {}) {
  const { testnet = false, bounceable = false } = options;
  
  if (!rawAddress) return '';
  
  // If already in user-friendly format (starts with UQ, EQ, kQ, 0Q)
  if (/^[UEk0]Q/.test(rawAddress)) {
    return rawAddress;
  }
  
  // If it's a raw address (0:hex or -1:hex)
  if (!rawAddress.includes(':')) {
    return rawAddress; // Not a valid raw address, return as is
  }
  
  try {
    const [workchainStr, hashPart] = rawAddress.split(':');
    const workchain = parseInt(workchainStr, 10);
    
    if (isNaN(workchain) || !hashPart || hashPart.length !== 64) {
      return rawAddress;
    }
    
    // Convert hex to bytes
    const hashBytes = hexToBytes(hashPart);
    
    // Create address bytes (34 bytes total):
    // Flag byte: 0x11 = bounceable mainnet, 0x51 = non-bounceable mainnet
    //           0x91 = bounceable testnet, 0xd1 = non-bounceable testnet
    let flags;
    if (testnet) {
      flags = bounceable ? 0x91 : 0x51; 
    } else {
      flags = bounceable ? 0x11 : 0x51; // Default to non-bounceable (UQ format)
    }
    
    const addressBytes = new Uint8Array(34);
    addressBytes[0] = flags;
    addressBytes[1] = workchain & 0xFF;
    addressBytes.set(hashBytes, 2);
    
    // Calculate CRC16
    const crc = crc16(addressBytes);
    
    // Create final bytes (36 bytes: 34 + 2 for CRC)
    const finalBytes = new Uint8Array(36);
    finalBytes.set(addressBytes);
    finalBytes[34] = (crc >> 8) & 0xFF;
    finalBytes[35] = crc & 0xFF;
    
    // Convert to base64url
    return bytesToBase64Url(finalBytes);
  } catch (e) {
    console.warn('Failed to convert address:', e);
    return rawAddress;
  }
}

/**
 * Convert hex string to Uint8Array
 */
function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
  }
  return bytes;
}

/**
 * Convert Uint8Array to base64url string
 */
function bytesToBase64Url(bytes) {
  // Convert to regular base64
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const base64 = btoa(binary);
  
  // Convert to base64url (replace + with -, / with _)
  return base64.replace(/\+/g, '-').replace(/\//g, '_');
}

/**
 * CRC16 XMODEM calculation for TON addresses
 */
function crc16(data) {
  const polynomial = 0x1021;
  let crc = 0;
  
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i] << 8;
    for (let j = 0; j < 8; j++) {
      if (crc & 0x8000) {
        crc = (crc << 1) ^ polynomial;
      } else {
        crc <<= 1;
      }
      crc &= 0xFFFF;
    }
  }
  
  return crc;
}

/**
 * Shorten address for display
 * @param {string} address - TON address
 * @param {number} startChars - Characters to show at start
 * @param {number} endChars - Characters to show at end
 * @returns {string} Shortened address
 */
export function shortenAddress(address, startChars = 6, endChars = 4) {
  if (!address) return '';
  if (address.length <= startChars + endChars) return address;
  return `${address.slice(0, startChars)}...${address.slice(-endChars)}`;
}

/**
 * Check if address is in user-friendly format
 * @param {string} address - Address to check
 * @returns {boolean}
 */
export function isUserFriendlyAddress(address) {
  if (!address) return false;
  return /^[UEk0]Q[A-Za-z0-9_-]{46}$/.test(address);
}

/**
 * Convert base64url to standard base64
 * TON Connect sometimes requires standard base64 addresses
 */
export function base64UrlToBase64(base64url) {
  if (!base64url) return '';
  return base64url.replace(/-/g, '+').replace(/_/g, '/');
}

/**
 * Normalize TON address for TON Connect transactions
 * Converts URL-safe base64 to standard base64 if needed
 */
export function normalizeAddressForTonConnect(address) {
  if (!address) return '';
  // If address contains _ or -, convert to standard base64
  if (address.includes('_') || address.includes('-')) {
    return base64UrlToBase64(address);
  }
  return address;
}

export default {
  getAddressHash,
  isSameTonAddress,
  toUserFriendlyAddress,
  shortenAddress,
  isUserFriendlyAddress,
  base64UrlToBase64,
  normalizeAddressForTonConnect
};
