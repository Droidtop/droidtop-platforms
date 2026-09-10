# controllers/

One file per pad, named `<vendorId>-<productId>.json` (lower-case hex, no
`0x`), for controllers whose Android mapping is wrong and which SDL's
`gamecontrollerdb` does not already correct.

The directory is deliberately empty. A profile is only worth shipping when
someone has captured it on the pad itself: a guessed mapping overrides a
mapping that may already be correct, and the person holding the pad has no
way to tell which of the two broke their controller. Enginehost's capture UI
produces exactly this shape from a real pad; that is where entries come from.
