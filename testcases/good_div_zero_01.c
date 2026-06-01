/* CWE-369: Divide By Zero (GOOD baseline)
 * Expected detection: none
 */
int main(void) {
    int a = 10;
    int b = a / 2;
    return b;
}
