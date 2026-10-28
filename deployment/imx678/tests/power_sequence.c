// SPDX-License-Identifier: GPL-2.0-only
// Exercise the actual patched functions with recorded kernel API calls.
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define I2C_LOCK_ROOT_ADAPTER 1
#define dev_err(...) ((void)0)
struct device { int unused; };
struct i2c_client { void *adapter; };
struct imx678 {
    void *bus_pinctrl, *bus_off, *bus_active, *reset_gpio, *xclk;
    int supplies[3];
};
static const char *imx678_supply_name[] = {"avdd", "dvdd", "ovdd"};
static struct imx678 sensor = {.bus_off = (void *)1, .bus_active = (void *)2};
static struct i2c_client client;
static char events[1024];
static const char *fail;
static bool locked;
static int record(const char *event)
{
    strcat(events, event);
    strcat(events, " ");
    return fail && !strcmp(fail, event) ? -EIO : 0;
}
static struct i2c_client *to_i2c_client(struct device *dev) { (void)dev; return &client; }
static void *i2c_get_clientdata(struct i2c_client *c) { (void)c; return &sensor; }
static struct imx678 *to_imx678(void *s) { return s; }
static void i2c_lock_bus(void *a, int b)
{
    (void)a; (void)b; assert(!locked); locked = true; record("lock");
}
static void i2c_unlock_bus(void *a, int b)
{
    (void)a; (void)b; assert(locked); locked = false; record("unlock");
}
static int pinctrl_select_state(void *p, void *s)
{
    (void)p; assert(locked); return record(s == sensor.bus_off ? "clamp" : "i2c");
}
static void gpiod_set_value_cansleep(void *g, int v)
{
    (void)g; assert(locked); record(v ? "reset-low" : "reset-high");
}
static int regulator_bulk_enable(unsigned long n, int *s)
{
    (void)n; (void)s; assert(locked); return record("power-on");
}
static int regulator_bulk_disable(unsigned long n, int *s)
{
    (void)n; (void)s; assert(locked); return record("power-off");
}
static int clk_prepare_enable(void *c) { (void)c; return record("clock-on"); }
static void clk_disable_unprepare(void *c) { (void)c; record("clock-off"); }
static void fsleep(unsigned long us)
{
    assert(locked);
    if (us == 1000) record("wait-1ms");
    else if (us == 5000) record("wait-5ms");
    else if (us == 150000) record("wait-150ms");
    else assert(false);
}
static int imx678_write_common(struct imx678 *s)
{
    (void)s; assert(!locked); return record("registers");
}

#include "power-sequence-under-test.h"

static void check(const char *failure, bool on, int expected, const char *trace)
{
    struct device dev;
    events[0] = '\0'; fail = failure;
    int result = on ? imx678_converter_power_on(&dev) : imx678_converter_power_off(&dev);
    if (result != expected || strcmp(events, trace)) {
        fprintf(stderr, "failure=%s result=%d trace=%s\n", failure, result, events);
        assert(false);
    }
    assert(!locked);
}

int main(void)
{
    const char *off = "lock clamp reset-low wait-1ms clock-off power-off wait-150ms unlock ";
    check(NULL, true, 0,
          "lock clamp reset-low power-on reset-high clock-on wait-5ms i2c unlock registers ");
    check(NULL, false, 0, off);
    check("clamp", true, -EIO, "lock clamp unlock ");
    check("clamp", false, -EIO, "lock clamp unlock ");
    check("power-on", true, -EIO, "lock clamp reset-low power-on unlock ");
    check("clock-on", true, -EIO,
          "lock clamp reset-low power-on reset-high clock-on reset-low wait-1ms power-off wait-150ms unlock ");
    check("i2c", true, -EIO,
          "lock clamp reset-low power-on reset-high clock-on wait-5ms i2c unlock "
          "lock clamp reset-low wait-1ms clock-off power-off wait-150ms unlock ");
    check("registers", true, -EIO,
          "lock clamp reset-low power-on reset-high clock-on wait-5ms i2c unlock registers "
          "lock clamp reset-low wait-1ms clock-off power-off wait-150ms unlock ");
    check("power-off", false, -EIO, off);
    puts("9 converter power sequencing / failure cases passed");
    return 0;
}
