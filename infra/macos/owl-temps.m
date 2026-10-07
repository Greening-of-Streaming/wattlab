// owl-temps — print Apple-silicon temperature sensors as JSON (no sudo).
// Reads the IOHID temperature services (usage page 0xff00, usage 5) that
// Activity-Monitor-class tools use. Build on the Mac:
//   clang -O2 -fobjc-arc -framework IOKit -framework Foundation owl-temps.m -o ~/owl/owl-temps
#import <Foundation/Foundation.h>
#include <IOKit/hidsystem/IOHIDEventSystemClient.h>

typedef struct __IOHIDEvent *IOHIDEventRef;
typedef struct __IOHIDServiceClient *IOHIDServiceClientRef;
IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(CFAllocatorRef);
int IOHIDEventSystemClientSetMatching(IOHIDEventSystemClientRef, CFDictionaryRef);
CFArrayRef IOHIDEventSystemClientCopyServices(IOHIDEventSystemClientRef);
IOHIDEventRef IOHIDServiceClientCopyEvent(IOHIDServiceClientRef, int64_t, int32_t, int64_t);
CFTypeRef IOHIDServiceClientCopyProperty(IOHIDServiceClientRef, CFStringRef);
double IOHIDEventGetFloatValue(IOHIDEventRef, int32_t);
#define kIOHIDEventTypeTemperature 15
#define FIELD(t) ((t) << 16)

int main(void) {
  @autoreleasepool {
    NSDictionary *match = @{@"PrimaryUsagePage": @0xff00, @"PrimaryUsage": @5};
    IOHIDEventSystemClientRef sys = IOHIDEventSystemClientCreate(kCFAllocatorDefault);
    IOHIDEventSystemClientSetMatching(sys, (__bridge CFDictionaryRef)match);
    NSArray *services = CFBridgingRelease(IOHIDEventSystemClientCopyServices(sys));
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    for (id s in services) {
      IOHIDServiceClientRef sc = (__bridge IOHIDServiceClientRef)s;
      NSString *name = CFBridgingRelease(IOHIDServiceClientCopyProperty(sc, CFSTR("Product")));
      IOHIDEventRef ev = IOHIDServiceClientCopyEvent(sc, kIOHIDEventTypeTemperature, 0, 0);
      if (!name || !ev) continue;
      double t = IOHIDEventGetFloatValue(ev, FIELD(kIOHIDEventTypeTemperature));
      CFRelease(ev);
      if (t > 0 && t < 150) {
        NSString *k = name; int i = 2;
        while (out[k]) k = [NSString stringWithFormat:@"%@ #%d", name, i++];
        out[k] = @(round(t * 10) / 10);
      }
    }
    NSData *j = [NSJSONSerialization dataWithJSONObject:out options:NSJSONWritingSortedKeys error:nil];
    fwrite(j.bytes, 1, j.length, stdout); fputc('\n', stdout);
    CFRelease(sys);
  }
  return 0;
}
