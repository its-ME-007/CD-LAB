/* CWE-457: Use of Uninitialized Variable (BAD, variant 2)
 * Expected detection: uninit
 * Variation: uninit used in a return-expression directly.
 */
int main(void) {
    int x;
    return x;       /* <-- uninit return value */
}
