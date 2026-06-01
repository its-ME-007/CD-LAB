/* CWE-369: Divide By Zero (BAD, variant 2)
 * Expected detection: div_zero
 * Variation: modulo by zero (also UB).
 */
int main(int argc, char **argv) {
    (void)argv;
    int result = 100 % 0;
    return result + argc;
}
