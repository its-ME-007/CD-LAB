// Phase 3 target: detector "null_deref" should flag line 5.
#include <stddef.h>

int main(void) {
    int *p = NULL;
    *p = 42;        // <-- null dereference
    return 0;
}
