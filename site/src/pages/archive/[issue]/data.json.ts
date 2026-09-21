export async function getStaticPaths() {
  const files = import.meta.glob('../../../data/archive/*.json', {eager:true});
  return Object.values(files).map((module:any)=>({params:{issue:module.default.issue_date},props:{edition:module.default}}));
}
export function GET({props}: {props:any}) {
  return new Response(JSON.stringify(props.edition, null, 2), {headers:{'Content-Type':'application/json; charset=utf-8'}});
}
