/* CWE-190: Integer Overflow (BAD)
 * Expected detection: int_overflow
 */
int main(void) {
    /* INT_MAX + 1 wraps signed integer overflow (UB in C) */
    int x = 2147483647 + 1;
    return x;
}
