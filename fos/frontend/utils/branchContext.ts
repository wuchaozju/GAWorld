export type BranchRouteContext = {
  nodeId: string | null;
  compareId: string | null;
};

const appendParam = (params: URLSearchParams, key: string, value: string | null) => {
  if (value) {
    params.set(key, value);
    return;
  }
  params.delete(key);
};

export const readBranchContext = (searchParams: URLSearchParams): BranchRouteContext => ({
  nodeId: searchParams.get("node"),
  compareId: searchParams.get("compare"),
});

export const buildBranchContextHref = (
  pathname: string,
  nodeId: string | null,
  compareId: string | null = null,
) => {
  const params = new URLSearchParams();
  appendParam(params, "node", nodeId);
  appendParam(params, "compare", compareId);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
};
