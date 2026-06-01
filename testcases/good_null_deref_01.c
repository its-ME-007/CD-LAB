/* CWE-476: NULL Pointer Dereference (GOOD baseline)
 * Expected detection: none
 */
#include <stddef.h>

int main(void) {
    int x = 42;
    int *p = &x;
    *p = 100;       /* safe — p points to a real object */
    return *p;
}
