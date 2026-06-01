/* CWE-457: Use of Uninitialized Variable (GOOD baseline)
 * Expected detection: none
 */
int main(void) {
    int x = 0;
    int y;
    y = x + 1;
    return y;
}
