/* CWE-369: Divide By Zero (BAD)
 * Expected detection: div_zero
 */
int main(void) {
    int a = 10;
    int b = a / 0;  /* <-- divisor is literal zero */
    return b;
}
