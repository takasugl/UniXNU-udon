/*
 * Read a USB Bulk-Only Transport mass-storage LUN without the macOS
 * IOUSBMassStorageDriver/IOMedia stack.
 *
 * usage: usb-bot-read OUT_FILE [VID PID]
 */
#include <libusb-1.0/libusb.h>

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BOT_CBW_SIGNATURE 0x43425355u
#define BOT_CSW_SIGNATURE 0x53425355u
#define BOT_TIMEOUT_MS    30000
#define READ_CHUNK_BYTES  65536u

struct bot_cbw {
  uint32_t signature;
  uint32_t tag;
  uint32_t transfer_length;
  uint8_t flags;
  uint8_t lun;
  uint8_t cdb_length;
  uint8_t cdb[16];
} __attribute__((packed));

struct bot_csw {
  uint32_t signature;
  uint32_t tag;
  uint32_t residue;
  uint8_t status;
} __attribute__((packed));

static void die(const char *what) {
  fprintf(stderr, "%s: %s\n", what, strerror(errno));
  exit(1);
}

static void be32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)(v >> 24);
  p[1] = (uint8_t)(v >> 16);
  p[2] = (uint8_t)(v >> 8);
  p[3] = (uint8_t)v;
}

static int bot_command(libusb_device_handle *dev, uint8_t ep_in, uint8_t ep_out,
                       uint32_t tag, const uint8_t *cdb, uint8_t cdb_length,
                       uint8_t *data, uint32_t data_length, int data_in) {
  struct bot_cbw cbw = {0};
  struct bot_csw csw = {0};
  int transferred = 0;
  int rc;

  cbw.signature = BOT_CBW_SIGNATURE;
  cbw.tag = tag;
  cbw.transfer_length = data_length;
  cbw.flags = data_in ? 0x80 : 0x00;
  cbw.lun = 0;
  cbw.cdb_length = cdb_length;
  memcpy(cbw.cdb, cdb, cdb_length);

  for (int attempt = 0; attempt < 2; attempt++) {
    rc = libusb_bulk_transfer(dev, ep_out, (uint8_t *)&cbw, sizeof(cbw),
                              &transferred, BOT_TIMEOUT_MS);
    if (rc == LIBUSB_SUCCESS && transferred == (int)sizeof(cbw)) {
      break;
    }
    fprintf(stderr, "CBW transfer attempt %d failed: %s (%d)\n",
            attempt + 1, libusb_error_name(rc), transferred);
    if (attempt != 0) {
      return -1;
    }
    usleep(500000);
  }

  if (data_length != 0) {
    rc = libusb_bulk_transfer(dev, data_in ? ep_in : ep_out, data, data_length,
                              &transferred, BOT_TIMEOUT_MS);
    if (rc != LIBUSB_SUCCESS || transferred != (int)data_length) {
      fprintf(stderr, "data transfer failed: %s (%d/%u)\n",
              libusb_error_name(rc), transferred, data_length);
      return -1;
    }
  }

  transferred = 0;
  rc = libusb_bulk_transfer(dev, ep_in, (uint8_t *)&csw, sizeof(csw),
                            &transferred, BOT_TIMEOUT_MS);
  if (rc != LIBUSB_SUCCESS || transferred != (int)sizeof(csw) ||
      csw.signature != BOT_CSW_SIGNATURE || csw.tag != tag) {
    fprintf(stderr, "CSW failed: %s (%d), sig=%08x tag=%08x status=%u\n",
            libusb_error_name(rc), transferred, csw.signature, csw.tag,
            csw.status);
    return -1;
  }

  if (csw.status != 0) {
    fprintf(stderr, "SCSI command %02x failed: CSW status=%u residue=%u\n",
            cdb[0], csw.status, csw.residue);
    return -1;
  }

  return 0;
}

int main(int argc, char **argv) {
  libusb_context *ctx = NULL;
  libusb_device **devices = NULL;
  libusb_device_handle *dev = NULL;
  struct libusb_config_descriptor *config = NULL;
  uint8_t ep_in = 0, ep_out = 0;
  uint16_t vid = 0x05c6, pid = 0xf000;
  uint8_t inquiry[36] = {0}, capacity[8] = {0};
  uint8_t cdb[16] = {0};
  uint8_t *chunk = NULL;
  uint32_t tag = 1, lba, last_lba, block_size, blocks;
  ssize_t count = 0;
  int rc, fd = -1;

  if (argc < 2) {
    fprintf(stderr, "usage: %s OUT_FILE [VID PID]\n", argv[0]);
    return 2;
  }
  if (argc >= 4) {
    vid = (uint16_t)strtoul(argv[2], NULL, 0);
    pid = (uint16_t)strtoul(argv[3], NULL, 0);
  }

  rc = libusb_init(&ctx);
  if (rc != LIBUSB_SUCCESS) {
    fprintf(stderr, "libusb_init: %s\n", libusb_error_name(rc));
    return 1;
  }

  count = libusb_get_device_list(ctx, &devices);
  for (ssize_t i = 0; i < count; i++) {
    struct libusb_device_descriptor desc;
    if (libusb_get_device_descriptor(devices[i], &desc) != LIBUSB_SUCCESS ||
        desc.idVendor != vid || desc.idProduct != pid) {
      continue;
    }
    rc = libusb_open(devices[i], &dev);
    if (rc != LIBUSB_SUCCESS) {
      fprintf(stderr, "open %04x:%04x: %s\n", vid, pid,
              libusb_error_name(rc));
      continue;
    }
    rc = libusb_set_auto_detach_kernel_driver(dev, 1);
    fprintf(stderr, "auto-detach: %s\n", libusb_error_name(rc));
    rc = libusb_detach_kernel_driver(dev, 0);
    fprintf(stderr, "detach interface 0: %s\n", libusb_error_name(rc));
    rc = libusb_claim_interface(dev, 0);
    if (rc == LIBUSB_SUCCESS) {
      break;
    }
    fprintf(stderr, "claim interface 0: %s\n", libusb_error_name(rc));
    libusb_close(dev);
    dev = NULL;
  }
  if (dev == NULL) {
    fprintf(stderr, "mass-storage device %04x:%04x not openable\n", vid, pid);
    return 1;
  }

  rc = libusb_get_active_config_descriptor(
      libusb_get_device(dev), &config);
  if (rc != LIBUSB_SUCCESS) {
    fprintf(stderr, "get config: %s\n", libusb_error_name(rc));
    return 1;
  }
  for (int i = 0; i < config->interface[0].num_altsetting; i++) {
    const struct libusb_interface_descriptor *alt =
        &config->interface[0].altsetting[i];
    for (int e = 0; e < alt->bNumEndpoints; e++) {
      const struct libusb_endpoint_descriptor *ep = &alt->endpoint[e];
      if ((ep->bmAttributes & LIBUSB_TRANSFER_TYPE_MASK) !=
          LIBUSB_TRANSFER_TYPE_BULK) {
        continue;
      }
      if ((ep->bEndpointAddress & LIBUSB_ENDPOINT_DIR_MASK) ==
          LIBUSB_ENDPOINT_IN) {
        ep_in = ep->bEndpointAddress;
      } else {
        ep_out = ep->bEndpointAddress;
      }
    }
    if (ep_in && ep_out) {
      break;
    }
  }
  if (!ep_in || !ep_out) {
    fprintf(stderr, "bulk endpoints not found\n");
    return 1;
  }
  fprintf(stderr, "using endpoint IN %02x OUT %02x\n", ep_in, ep_out);
  usleep(1000000);

  cdb[0] = 0x12;
  cdb[4] = sizeof(inquiry);
  if (bot_command(dev, ep_in, ep_out, tag++, cdb, 6, inquiry,
                  sizeof(inquiry), 1) != 0) {
    return 1;
  }

  memset(cdb, 0, sizeof(cdb));
  cdb[0] = 0x25;
  if (bot_command(dev, ep_in, ep_out, tag++, cdb, 10, capacity,
                  sizeof(capacity), 1) != 0) {
    return 1;
  }
  last_lba = ((uint32_t)capacity[0] << 24) | ((uint32_t)capacity[1] << 16) |
             ((uint32_t)capacity[2] << 8) | capacity[3];
  block_size = ((uint32_t)capacity[4] << 24) |
               ((uint32_t)capacity[5] << 16) |
               ((uint32_t)capacity[6] << 8) | capacity[7];
  if (block_size != 512) {
    fprintf(stderr, "unexpected block size %u\n", block_size);
    return 1;
  }
  blocks = last_lba + 1;
  fprintf(stderr, "capacity: %u blocks x %u bytes = %llu bytes\n",
          blocks, block_size, (unsigned long long)blocks * block_size);

  fd = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (fd < 0) {
    die("open output");
  }
  chunk = malloc(READ_CHUNK_BYTES);
  if (chunk == NULL) {
    die("malloc");
  }

  for (lba = 0; lba < blocks;) {
    uint32_t n = blocks - lba;
    if (n > READ_CHUNK_BYTES / block_size) {
      n = READ_CHUNK_BYTES / block_size;
    }
    memset(cdb, 0, sizeof(cdb));
    cdb[0] = 0x28;
    be32(&cdb[2], lba);
    cdb[7] = (uint8_t)(n >> 8);
    cdb[8] = (uint8_t)n;
    if (bot_command(dev, ep_in, ep_out, tag++, cdb, 10, chunk,
                    n * block_size, 1) != 0) {
      return 1;
    }
    if (write(fd, chunk, n * block_size) != (ssize_t)(n * block_size)) {
      die("write output");
    }
    lba += n;
    if ((lba % 8192) < n) {
      fprintf(stderr, "read %u/%u blocks\n", lba, blocks);
    }
  }

  close(fd);
  free(chunk);
  libusb_free_config_descriptor(config);
  libusb_release_interface(dev, 0);
  libusb_close(dev);
  libusb_free_device_list(devices, 1);
  libusb_exit(ctx);
  return 0;
}
