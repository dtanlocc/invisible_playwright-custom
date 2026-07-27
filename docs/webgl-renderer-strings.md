# Firefox WebGL renderer strings: what ANGLE reports, and why a plausible one is harder than a random one

Two strings decide more than people expect:

```js
const gl = document.createElement('canvas').getContext('webgl');
const dbg = gl.getExtension('WEBGL_debug_renderer_info');
gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);    // "Google Inc. (NVIDIA)"
gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);  // "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)"
```

They name your graphics hardware. Not a hash, not a score: the actual model. That
makes them one of the few fingerprint surfaces where being *wrong* is obvious and
being *unusual* is enough on its own.

## Why Firefox says "ANGLE" and "Google Inc."

This surprises people, and getting it wrong is a common tell in spoofed profiles.

On Windows, Firefox does not talk to the OpenGL driver directly. It uses **ANGLE**,
Google's translation layer, which turns OpenGL ES calls into Direct3D 11. Firefox
adopted it for the same reason Chrome did: Windows OpenGL drivers were unreliable and
D3D11 was not.

So on Windows a real Firefox reports a vendor of `Google Inc. (NVIDIA)` or
`Google Inc. (Intel)`, and a renderer that begins `ANGLE (`. Not `Mozilla`. A profile
that "corrects" this to something Mozilla-branded has made itself unusual in a way no
real installation is.

The shape is stable and worth knowing by heart:

```
ANGLE (<vendor>, <device> Direct3D11 vs_<major>_<minor> ps_<major>_<minor>, D3D11)
```

`vs_` and `ps_` are the vertex and pixel shader model the device supports. They are
not decoration: they correlate with how old the GPU is, and a modern card claiming
`vs_4_0` is as inconsistent as a modern card claiming 512 MB of memory.

On Linux the string is a plain GL renderer instead, and on macOS it names the Apple
GPU. The platform you claim and the shape of this string have to agree, and that is
one comparison, not two independent values.

## The failure mode nobody plans for

Not "an unusual GPU". A **software** one.

When Windows has no working GPU driver, which is the normal state of a virtual
machine or a bare server, it falls back to a software rasterizer and WebGL reports:

```
ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11)
```

On Linux the equivalents are `llvmpipe` and `SwiftShader`. Any of them is the browser
announcing, in plain text, that it is running on a machine with no graphics hardware.
Almost nobody browses that way. It correlates with datacenters about as strongly as
anything in a fingerprint does, and no amount of patching elsewhere hides it, because
it is not a lie you told: it is the truth about where you are.

That is the part worth internalising. Most fingerprinting advice is about hiding
automation. This is about hiding a *server*, and the two need different fixes.

## How a real one gets into a fake profile, from our own logs

A cautionary tale, because we shipped this.

This project generates its fingerprint by sampling from pools built out of real
telemetry, on the theory that values seen in the wild are the safest values to claim.
Real telemetry, from real users, includes people running Windows on virtual machines.
So the software rasterizer was in the pool, sampled at its true real-world frequency,
and about **1.4% of seeds drew it**: 21 out of 1,500 sampled.

Sampling faithfully from reality had reproduced reality's worst case.

It was worse than 1.4% suggests, because seed 42 was one of the 21, and seed 42 was
the example seed in the class docstring. Anyone copying the quickstart got a browser
announcing it had no GPU.

The fix was to replace that entry in place rather than delete it, so only the seeds
that drew it changed and every other identity stayed stable. It is now zero out of
1,500, and the share it held moved to an ordinary Intel integrated GPU.

The general lesson, if you build one of these: **a pool sampled from real data still
needs a rule about what is disqualifying**. "Real users have this" and "you should
claim this" are different questions.

## Checking your own

Paste the two lines at the top into any console. What you want to see:

- The vendor and renderer agree with the platform you claim, including the ANGLE
  shape on Windows.
- The device is consumer hardware someone could buy, and its shader model is
  plausible for its generation.
- Nothing says basic, software, llvmpipe or SwiftShader.
- The GPU is consistent with the rest of the claim: a machine reporting four cores
  and 8 GB with a workstation card is a combination that mostly does not exist.

And check it on the machine that will actually run the job, not on your laptop. This
is precisely the value that differs between the two, which is why it catches people
who tested locally and deployed to a VM.

## Why spoofing this one from JavaScript is weak

You can override `getParameter` in the page. It works against a check that asks once
and believes the answer.

It does not survive much else. The override is a function whose source can be
printed, and its result can be cross-checked against things that are harder to fake:
the actual rendering of a canvas, the set of supported extensions, the reported
maximum texture size, the shader precision ranges. A claimed NVIDIA card whose
extension list belongs to a software rasterizer has answered the same question twice
and given different answers.

Setting these values in the browser's own source avoids that, since there is no
override to find and the derived values can be made to agree by construction. It is
also considerably more work, and it is why projects in this space end up patching
engines rather than pages.

**See also:** [why headless renders different fonts](headless-fonts-differ.md), the same class of server tell, and [what sannysoft checks](sannysoft-explained.md), where two of the eleven rows are these strings.

---

*From the notes of [invisible_playwright](https://github.com/feder-cr/invisible_playwright),
a Firefox patched at the C++ level. The 1.4% above is our own measurement, of our own
mistake.*
