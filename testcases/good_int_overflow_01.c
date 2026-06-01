/* CWE-190: Integer Overflow (GOOD baseline)
 * Expected detection: none
 */
int main(void) {
    int x = 100 + 1;
    return x;
}
