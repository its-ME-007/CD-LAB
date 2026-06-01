/* CWE-457: Use of Uninitialized Variable (BAD)
 * Expected detection: uninit
 */
int main(void) {
    int x;          /* declared, never initialized */
    int y;
    y = x + 1;      /* <-- reads uninitialized x */
    return y;
}
