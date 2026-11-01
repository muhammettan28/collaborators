import { beforeEach, describe, expect, it, vi } from 'vitest';

const lookup = vi.fn();
vi.mock('node:dns/promises', () => ({ lookup }));

const { isAllowedRequest, isPublicAddress } = await import('../src/network.js');

describe('isPublicAddress', () => {
  it.each([
    ['93.184.215.14', true],
    ['8.8.8.8', true],
    ['10.1.2.3', false],
    ['172.20.0.5', false],
    ['192.168.1.1', false],
    ['127.0.0.1', false],
    ['169.254.169.254', false],
    ['100.64.0.1', false],
    ['0.0.0.0', false],
    ['2606:4700::1', true],
    ['::1', false],
    ['fe80::1', false],
    ['fd00::1', false],
    ['::ffff:10.0.0.1', false],
  ])('%s → %s', (address, expected) => {
    expect(isPublicAddress(address)).toBe(expected);
  });
});

describe('isAllowedRequest', () => {
  beforeEach(() => lookup.mockReset());

  it('lets in what the file carries', async () => {
    expect(await isAllowedRequest('data:image/png;base64,AAAA')).toBe(true);
    expect(await isAllowedRequest('blob:null/1234')).toBe(true);
  });

  it('lets in https on the public internet', async () => {
    lookup.mockResolvedValue([{ address: '104.16.1.1', family: 4 }]);
    expect(await isAllowedRequest('https://cdnjs.cloudflare.com/x.js')).toBe(true);
  });

  it("refuses this server's network, plain http and other ports", async () => {
    lookup.mockResolvedValue([{ address: '10.0.0.7', family: 4 }]);
    expect(await isAllowedRequest('https://sneaky.example.org/x')).toBe(false);
    expect(await isAllowedRequest('https://backend/api/v1.0/')).toBe(false);
    expect(await isAllowedRequest('https://127.0.0.1/')).toBe(false);
    expect(await isAllowedRequest('http://example.org/')).toBe(false);
    expect(await isAllowedRequest('https://example.org:8000/')).toBe(false);
    expect(await isAllowedRequest('file:///etc/passwd')).toBe(false);
    expect(await isAllowedRequest('not a url')).toBe(false);
  });

  it('refuses a name answering with a public and a private address', async () => {
    lookup.mockResolvedValue([
      { address: '93.184.215.14', family: 4 },
      { address: '192.168.0.2', family: 4 },
    ]);
    expect(await isAllowedRequest('https://mixed.example.org/')).toBe(false);
  });

  it('refuses names that lead nowhere', async () => {
    lookup.mockResolvedValue([]);
    expect(await isAllowedRequest('https://nowhere.example.org/')).toBe(false);
  });
});
