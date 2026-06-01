/* CWE-476: NULL Pointer Dereference (BAD, variant 2)
 * Expected detection: null_deref
 * Variation: assignment after declaration, not in initializer.
 */
int main(void) {
    int *p;
    p = 0;
    *p = 1;         /* <-- deref via reassignment to NULL */
    return 0;
}
