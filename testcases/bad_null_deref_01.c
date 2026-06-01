/* CWE-476: NULL Pointer Dereference (BAD)
 * Expected detection: null_deref
 */
#include <stddef.h>

int main(void) {
    int *p = NULL;
    *p = 42;        /* <-- null pointer dereferenced */
    return 0;
}
