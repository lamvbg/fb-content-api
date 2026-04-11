"""
A-Bogus parameter generator for Douyin Web API.
Ported from https://github.com/Evil0ctal/Douyin_TikTok_Download_API
Original algorithm by https://github.com/JoeanAmier/TikTokDownloader (GPL v3)
"""

from random import randint, random
from re import compile
from time import time
from urllib.parse import urlencode, quote

from gmssl import sm3, func

__all__ = ["ABogus"]


class ABogus:
    __filter = compile(r"%([0-9A-F]{2})")
    __arguments = [0, 1, 14]
    __end_string = "cus"
    __browser = "1536|742|1536|864|0|0|0|0|1536|864|1536|864|1536|742|24|24|Win32"
    __reg = [
        1937774191, 1226093241, 388252375, 3666478592,
        2842636476, 372324522, 3817729613, 2969243214,
    ]
    __str = {
        "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
    }

    def __init__(self):
        self.chunk = []
        self.size = 0
        self.reg = self.__reg[:]
        # Hardcoded UA code for Chrome/90.0.4430.212
        self.ua_code = [
            76, 98, 15, 131, 97, 245, 224, 133, 122, 199, 241, 166,
            79, 34, 90, 191, 128, 126, 122, 98, 66, 11, 14, 40,
            49, 110, 110, 173, 67, 96, 138, 252,
        ]
        self.browser = self.__browser
        self.browser_len = len(self.browser)
        self.browser_code = [ord(c) for c in self.browser]

    # ── Random list generators ────────────────────────────────────────────

    @staticmethod
    def _random_list(a=None, b=170, c=85, d=0, e=0, f=0, g=0):
        r = a or (random() * 10000)
        v1 = int(r) & 255
        v2 = int(r) >> 8
        return [v1 & b | d, v1 & c | e, v2 & b | f, v2 & c | g]

    @classmethod
    def _list_1(cls, n=None):
        return cls._random_list(n, 170, 85, 1, 2, 5, 45 & 170)

    @classmethod
    def _list_2(cls, n=None):
        return cls._random_list(n, 170, 85, 1, 0, 0, 0)

    @classmethod
    def _list_3(cls, n=None):
        return cls._random_list(n, 170, 85, 1, 0, 5, 0)

    # ── SM3 hashing ───────────────────────────────────────────────────────

    @staticmethod
    def _sm3_to_array(data):
        if isinstance(data, str):
            b = data.encode("utf-8")
        else:
            b = bytes(data)
        h = sm3.sm3_hash(func.bytes_to_list(b))
        return [int(h[i : i + 2], 16) for i in range(0, len(h), 2)]

    def _gen_params_code(self, params: str):
        return self._sm3_to_array(self._sm3_to_array(params + self.__end_string))

    def _gen_method_code(self, method: str = "GET"):
        return self._sm3_to_array(self._sm3_to_array(method + self.__end_string))

    # ── SM3 compress (for RC4 input) ──────────────────────────────────────

    @staticmethod
    def _de(e, r):
        r %= 32
        return ((e << r) & 0xFFFFFFFF) | (e >> (32 - r))

    @staticmethod
    def _pe(e):
        return 2043430169 if 0 <= e < 16 else 2055708042

    @staticmethod
    def _he(e, r, t, n):
        if 0 <= e < 16:
            return (r ^ t ^ n) & 0xFFFFFFFF
        return (r & t | r & n | t & n) & 0xFFFFFFFF

    @staticmethod
    def _ve(e, r, t, n):
        if 0 <= e < 16:
            return (r ^ t ^ n) & 0xFFFFFFFF
        return (r & t | ~r & n) & 0xFFFFFFFF

    # ── RC4 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _rc4_encrypt(plaintext, key):
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + ord(key[i % len(key)])) % 256
            s[i], s[j] = s[j], s[i]
        i = j = 0
        cipher = []
        for k in range(len(plaintext)):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            t = (s[i] + s[j]) % 256
            cipher.append(chr(s[t] ^ ord(plaintext[k])))
        return "".join(cipher)

    # ── Core generation ───────────────────────────────────────────────────

    @staticmethod
    def _from_char_code(*args):
        return "".join(chr(c) for c in args)

    def _gen_string_1(self):
        return (
            self._from_char_code(*self._list_1())
            + self._from_char_code(*self._list_2())
            + self._from_char_code(*self._list_3())
        )

    @staticmethod
    def _list_4(a, b, c, d, e, f, g, h, i, j, k, m, n, o, p, q, r):
        return [
            44, a, 0, 0, 0, 0, 24, b, n, 0, c, d, 0, 0, 0, 1,
            0, 239, e, o, f, g, 0, 0, 0, 0, h, 0, 0, 14, i, j,
            0, k, m, 3, p, 1, q, 1, r, 0, 0, 0,
        ]

    @staticmethod
    def _end_check_num(a):
        r = 0
        for i in a:
            r ^= i
        return r

    @classmethod
    def _decode_string(cls, url_string):
        return cls.__filter.sub(lambda m: chr(int(m.group(1), 16)), url_string)

    def _gen_string_2(self, url_params, method="GET", start_time=0, end_time=0):
        start_time = start_time or int(time() * 1000)
        end_time = end_time or (start_time + randint(4, 8))
        params_array = self._gen_params_code(url_params)
        method_array = self._gen_method_code(method)

        a = self._list_4(
            (end_time >> 24) & 255, params_array[21], self.ua_code[23],
            (end_time >> 16) & 255, params_array[22], self.ua_code[24],
            (end_time >> 8) & 255, (end_time >> 0) & 255,
            (start_time >> 24) & 255, (start_time >> 16) & 255,
            (start_time >> 8) & 255, (start_time >> 0) & 255,
            method_array[21], method_array[22],
            int(end_time / 256 / 256 / 256 / 256) >> 0,
            int(start_time / 256 / 256 / 256 / 256) >> 0,
            self.browser_len,
        )
        e = self._end_check_num(a)
        a.extend(self.browser_code)
        a.append(e)
        return self._rc4_encrypt(self._from_char_code(*a), "y")

    @classmethod
    def _encode_result(cls, s, e="s4"):
        r = []
        for i in range(0, len(s), 3):
            if i + 2 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8) | ord(s[i + 2])
            elif i + 1 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8)
            else:
                n = ord(s[i]) << 16
            for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
                if j == 6 and i + 1 >= len(s):
                    break
                if j == 0 and i + 2 >= len(s):
                    break
                r.append(cls.__str[e][(n & k) >> j])
        r.append("=" * ((4 - len(r) % 4) % 4))
        return "".join(r)

    # ── Public API ────────────────────────────────────────────────────────

    def get_value(self, url_params, method="GET") -> str:
        """Generate a_bogus value for the given URL params."""
        s1 = self._gen_string_1()
        param_str = urlencode(url_params) if isinstance(url_params, dict) else url_params
        s2 = self._gen_string_2(param_str, method)
        return self._encode_result(s1 + s2, "s4")

    @classmethod
    def generate(cls, params: dict, method: str = "GET") -> str:
        """Convenience: generate URL-safe a_bogus value."""
        return quote(cls().get_value(params, method), safe="")
