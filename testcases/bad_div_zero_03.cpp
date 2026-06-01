/* CWE-369: Divide By Zero (BAD)
 * C++ idiom: divisor variable provably zero on all paths.
 * Expected detection: div_zero
 */
int main() {
    int d = 0;
    return 100 / d;     /* <-- d is always 0 here */
}
