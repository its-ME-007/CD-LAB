/* CWE-416: Use After Free (GOOD baseline)
 * Expected detection: none
 */
int main(void) {
    int *p = new int(7);
    int x = *p;     /* read first */
    delete p;
    p = nullptr;    /* clear so we can't accidentally reuse */
    return x;
}
