import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';

// What the browser may fetch while drawing a presentation: data the file
// carries, and https addresses on the public internet. Never this server's
// own network (the backend, the database, the files), whatever the file asks;
// the sealed document's rules already refuse its own requests, this is the
// second lock.

const PRIVATE_V4: [number, number][] = [
  // [network, prefix length]
  [0x00000000, 8], // 0.0.0.0/8
  [0x0a000000, 8], // 10.0.0.0/8
  [0x64400000, 10], // 100.64.0.0/10 (carrier NAT)
  [0x7f000000, 8], // loopback
  [0xa9fe0000, 16], // link-local, cloud metadata
  [0xac100000, 12], // 172.16.0.0/12
  [0xc0000000, 24], // 192.0.0.0/24
  [0xc0a80000, 16], // 192.168.0.0/16
  [0xc6120000, 15], // 198.18.0.0/15
  [0xe0000000, 3], // multicast and reserved
];

const v4ToNumber = (address: string) =>
  address
    .split('.')
    .reduce((total, part) => total * 256 + Number(part), 0) >>> 0;

/** Whether an address is on the public internet. */
export const isPublicAddress = (address: string): boolean => {
  if (isIP(address) === 4) {
    const value = v4ToNumber(address);
    return !PRIVATE_V4.some(([network, bits]) => {
      const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
      return (value & mask) >>> 0 === network;
    });
  }
  if (isIP(address) === 6) {
    const lower = address.toLowerCase();
    const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(lower);
    if (mapped) {
      return isPublicAddress(mapped[1]);
    }
    // global unicast only (2000::/3), which excludes loopback, link-local,
    // unique local (fc00::/7) and the rest
    return /^[23][0-9a-f]{0,3}:/.test(lower);
  }
  return false;
};

const decided = new Map<string, Promise<boolean>>();

const hostIsPublic = (host: string): Promise<boolean> => {
  let answer = decided.get(host);
  if (!answer) {
    answer = (async () => {
      if (isIP(host)) {
        return isPublicAddress(host);
      }
      if (!host.includes('.')) {
        // a name of this server's network (backend, minio…)
        return false;
      }
      try {
        const found = await lookup(host, { all: true });
        return found.length > 0 && found.every((a) => isPublicAddress(a.address));
      } catch {
        return false;
      }
    })().catch(() => false);
    decided.set(host, answer);
    // looked up again after a minute
    setTimeout(() => decided.delete(host), 60_000).unref();
  }
  return answer;
};

/** Whether the browser may make this request. */
export const isAllowedRequest = async (url: string): Promise<boolean> => {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (['data:', 'blob:', 'about:'].includes(parsed.protocol)) {
    return true;
  }
  if (parsed.protocol !== 'https:' || parsed.port) {
    return false;
  }
  return hostIsPublic(parsed.hostname.replace(/^\[|\]$/g, ''));
};
