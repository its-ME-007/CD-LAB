/* CWE-416: Use After Free (GOOD / true negative)
 * C++ idiom: new/delete with no access after the delete.
 * Expected detection: none
 */
int main() {
    int* p = new int(7);
    *p = 10;            /* used while still valid */
    delete p;
    return 0;
}
