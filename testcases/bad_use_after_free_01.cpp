/* CWE-416: Use After Free (BAD)
 * Expected detection: use_after_free
 */
int main(void) {
    int *p = new int(7);
    delete p;
    int x = *p;     /* <-- p was deleted above */
    return x;
}
