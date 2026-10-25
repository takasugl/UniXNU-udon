# Reproducing the Udon build

This repository pins the non-public state needed to reproduce the current
bring-up tree. Apple IPSW contents, the platform seed and generated images stay
outside Git.

## Host requirements

- macOS with Xcode command-line tools and an iPhoneOS SDK able to build XNU;
- Python 3.11 or newer;
- the host tools documented by UniXNU (`llvm`, `lld`, `cmake`, `ninja`,
  `mtools`, `dtc`);
- enough disk space for the XNU source tree, IPSW components, a 9.4 GiB
  `userdata` image and build output.

## 1. Fetch the pinned core

From this repository:

```sh
./scripts/bootstrap-core.sh ../UniXNU
```

The script:

1. checks out UniXNU commit
   `0597c81b4d571f4706f7bbcf03ca51fe5b6e868b`;
2. initializes NativeUfs at commit
   `04b748e613d6d34f6e7868d714db36184722924d`;
3. applies the core and NativeUfs patches in `integration/`;
4. copies the Udon diagnostic patches and core tools into the checkout.

The script refuses to modify a dirty core checkout.

## 2. Fetch UniXNU sources and the target image

```sh
cd ../UniXNU
./unixnu fetch -D ../UniXNU-udon
./unixnu build userdata -D ../UniXNU-udon --dry-run
./unixnu build userdata -D ../UniXNU-udon
```

The target is the unchanged iPad7,1 iPadOS 17.7.11 image (`21H461`). Its
download URL and expected component hashes are in `board.toml`.

## 3. Build the kernel

```sh
./unixnu defconfig udon_defconfig -D ../UniXNU-udon
./unixnu build kernel -D ../UniXNU-udon
python3 scripts/udon-patch-root-auth-skip.py out/udon/kernel/kernel.macho
```

The final command is a bring-up patch, not a production trust policy.

## 4. Build the payload

Build the combined static + System trust cache from the user's own IPSW:

```sh
python3 scripts/build-trustcache-container.py \
  --output out/ipsw/tc-raw/static-system.container \
  out/ipsw/tc-raw/static.trustcache \
  out/ipsw/tc-raw/system.trustcache
```

Generate the 32 MiB Data seed from the target OS volume:

```sh
python3 scripts/prepare-owner-data-fixture.py \
  --output build/owner-data-fixture
```

Then build the payload with an external platform seed:

```sh
./unixnu build payload -D ../UniXNU-udon \
  --unique-chip-id "${UNIXNU_UNIQUE_CHIP_ID}" \
  --trust-cache out/ipsw/tc-raw/static-system.container \
  --data-ramdisk build/owner-data-fixture/owner-data-32.cdr
```

The expected output is 96 MiB:

```text
out/udon/payload/payload.img
```

Verify the hashes recorded in `out/udon/payload/payload.json`; the build report
does not claim that the payload was run on hardware.

## 5. Build the firmware

Clone the companion `uefi-udon` repository, populate its vendor binaries from
the user's own PHK110 firmware dump, and follow
`uefi-udon/scripts/build-udon-firmware.sh`.

## 6. Checks

```sh
python3 scripts/check-repository.py
```

This covers source presence, board invariants, pinned commits, forbidden
artifacts, Python syntax and shell syntax. Real hardware evidence must be
recorded separately.
